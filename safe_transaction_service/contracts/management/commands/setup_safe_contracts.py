import logging

from django.core.files import File
from django.core.management import BaseCommand, CommandError

from safe_eth.eth import get_auto_ethereum_client
from safe_eth.safe.safe_deployments import safe_deployments

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

        for version in versions:
            for contract_name, addresses in safe_deployments[version].items():
                for contract_address in addresses.get(str(chain_id), []):
                    display_name = generate_safe_contract_display_name(
                        contract_name, version
                    )
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
