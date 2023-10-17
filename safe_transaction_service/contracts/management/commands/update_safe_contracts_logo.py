from django.core.files import File
from django.core.management import BaseCommand, CommandError

from gnosis.eth import EthereumClientProvider
from gnosis.safe.safe_deployments import safe_deployments

from safe_transaction_service.contracts.models import Contract


def generate_safe_contract_display_name(contract_name: str, version: str) -> str:
    """
    Generates the display name for Safe contract.
    Append Safe at the beginning if the contract name doesn't contain Safe word and append the contract version at the end.

    :param contract_name:
    :param version:
    :return: display_name
    """
    if "safe" not in contract_name.lower():
        return f"Safe: {contract_name} {version}"
    else:
        return f"{contract_name} {version}"


class Command(BaseCommand):
    help = "Update or create Safe contracts with provided logo"

    def add_arguments(self, parser):
        parser.add_argument(
            "--safe-version", type=str, help="Contract version", required=False
        )
        parser.add_argument(
            "--logo-path", type=str, help="Path of new logo", required=True
        )

    def handle(self, *args, **options):
        """
        Command to create or update Safe contracts with provided logo.

        :param args:
        :param options: Safe version and logo path
        :return:
        """
        safe_version = options["safe_version"]
        logo_path = options["logo_path"]
        ethereum_client = EthereumClientProvider()
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

        for version in versions:
            for contract_name, addresses in safe_deployments[version].items():
                contract, created = Contract.objects.get_or_create(
                    address=addresses[str(chain_id)],
                    defaults={
                        "name": contract_name,
                        "display_name": generate_safe_contract_display_name(
                            contract_name, version
                        ),
                    },
                )

                contract.logo.save(f"{contract.address}.png", logo_file)
                contract.save()
