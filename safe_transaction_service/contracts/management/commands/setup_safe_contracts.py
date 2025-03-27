import logging
from typing import List, Tuple

from django.core.files import File
from django.core.management import BaseCommand, CommandError

from safe_eth.eth import EthereumClient, get_auto_ethereum_client
from safe_eth.safe.safe_deployments import default_safe_deployments, safe_deployments

from config.settings.base import STATICFILES_DIRS
from safe_transaction_service.contracts.models import Contract

logger = logging.getLogger(__name__)

TRUSTED_FOR_DELEGATE_CALL = [
    "MultiSendCallOnly",
    "SignMessageLib",
    "SafeMigration",
]


def generate_safe_contract_display_name(contract_name: str, version: str) -> str:
    """
    Generates the display name for Safe contract.
    Append Safe at the beginning if the contract name doesn't contain Safe word and append the contract version at the end.

    :param contract_name:
    :param version:
    :return: display_name
    """
    # Remove gnosis word
    contract_name = contract_name.replace("Gnosis", "")
    if "safe" not in contract_name.lower():
        return f"Safe: {contract_name} {version}"
    else:
        return f"{contract_name} {version}"


class Command(BaseCommand):
    help = "Create or update the Safe contracts with default data. A different logo can be provided"

    def add_arguments(self, parser):
        parser.add_argument(
            "--safe-version", type=str, help="Contract version", required=False
        )
        parser.add_argument(
            "--force-update-contracts",
            help="Update all the information related to the Safe contracts",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--logo-path",
            type=str,
            help="Path of new logo",
            required=False,
            default=f"{STATICFILES_DIRS[0]}/safe/safe_contract_logo.png",
        )

    def handle(self, *args, **options):
        """
        Command to create or update Safe contracts with default data. A different contract logo can be provided.

        :param args:
        :param options: Safe version and logo path
        :return:
        """
        safe_version = options["safe_version"]
        force_update_contracts = options["force_update_contracts"]
        logo_path = options["logo_path"]
        ethereum_client = get_auto_ethereum_client()
        chain_id = ethereum_client.get_chain_id()
        logo_file = File(open(logo_path, "rb"))
        if not safe_version:
            versions = list(safe_deployments.keys())
        elif safe_version in safe_deployments:
            versions = [safe_version]
        else:
            raise CommandError(
                f"Wrong Safe version {safe_version}, supported versions {safe_deployments.keys()}"
            )

        if force_update_contracts:
            # update all safe contract names
            queryset = Contract.objects.update_or_create
        else:
            # only update the contracts with empty values
            queryset = Contract.objects.get_or_create

        if not (
            chain_deployments := self._get_deployments_by_chain_and_version(
                versions, str(chain_id)
            )
        ):
            # If the chain is not listed on safe_deployments, then Search on chain
            logger.warning("Creating default Safe contracts from chain")

            chain_deployments = self._get_default_deployments_by_version_on_chain(
                versions, ethereum_client
            )

        if chain_deployments:
            self._create_or_update_contracts_from_deployments(
                chain_deployments, queryset, force_update_contracts, logo_file
            )
        else:
            logger.warning(f"No deployment was found for the network {chain_id}")

    @staticmethod
    def _get_deployments_by_chain_and_version(
        versions: List[str], chain_id: str
    ) -> List[Tuple[str, str, str]]:
        """
        Get the list of contracts for the given versions and chain.

        :param versions: list of versions
        :param chain_id: chain id
        :return: list of (version, contract_name, contract_address)
        """
        chain_deployments: List[Tuple[str, str, str]] = []
        for version in versions:
            for contract_name, addresses in safe_deployments[version].items():
                for contract_address in addresses.get(chain_id, []):
                    chain_deployments.append((version, contract_name, contract_address))

        return chain_deployments

    @staticmethod
    def _get_default_deployments_by_version_on_chain(
        versions: List[str], ethereum_client: EthereumClient
    ) -> List[Tuple[str, str, str]]:
        """
        Get the default deployments by version actually deployed on chain.

        :param versions: list of versions
        :param ethereum_client: Ethereum client
        :return: list of (version, contract_name, contract_address)
        """
        chain_deployments: List[Tuple[str, str, str]] = []
        for version in versions:
            for contract_name, addresses in default_safe_deployments[version].items():
                for contract_address in addresses:
                    if ethereum_client.is_contract(contract_address):
                        chain_deployments.append(
                            (version, contract_name, contract_address)
                        )

        return chain_deployments

    @staticmethod
    def _create_or_update_contracts_from_deployments(
        deployments: List[Tuple[str, str, str]],
        queryset,
        force_update_contracts: bool,
        logo_file: File,
    ) -> None:
        """
        Create or update contracts from given deployments list.
        """
        for version, contract_name, contract_address in deployments:
            display_name = generate_safe_contract_display_name(contract_name, version)
            contract, created = queryset(
                address=contract_address,
                defaults={
                    "name": contract_name,
                    "display_name": display_name,
                    "trusted_for_delegate_call": contract_name
                    in TRUSTED_FOR_DELEGATE_CALL,
                },
            )

            if not created:
                # Remove previous logo file
                contract.logo.delete(save=True)
                # update name only for contracts with empty names
                if not force_update_contracts and contract.name == "":
                    contract.display_name = display_name
                    contract.name = contract_name

            try:
                contract.logo.save(f"{contract.address}.png", logo_file)
                contract.save()
            except OSError:
                logger.warning("Logo cannot be stored.")
