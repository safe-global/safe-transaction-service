from django.core.files import File
from django.core.management import BaseCommand, CommandError

from gnosis.eth import EthereumClientProvider
from gnosis.safe.safe_deployments import safe_deployments

from safe_transaction_service.contracts.models import Contract


def get_deployment_addresses(safe_deployments: dict, chain_id: str) -> list:
    """
    Return the deployment addresses of passed dict for a chain id.
    :param safe_deployments:
    :param chain_id:
    :return:
    """
    addresses = []
    if isinstance(safe_deployments, dict):
        for key, value in safe_deployments.items():
            if isinstance(value, dict):
                addresses.extend(get_deployment_addresses(value, chain_id))
            elif key == chain_id:
                addresses.append(value)
    return addresses


class Command(BaseCommand):
    help = "Update safe contract logos by new one"

    def add_arguments(self, parser):
        parser.add_argument(
            "--safe-version", type=str, help="Contract version", required=False
        )
        parser.add_argument(
            "--logo-path", type=str, help="Path of new logo", required=True
        )

    def handle(self, *args, **options):
        """
        Command to add or update safe contract logos if exist.
        :param args:
        :param options: safe version and logo path
        :return:
        """
        safe_version = options["safe_version"]
        logo_path = options["logo_path"]
        ethereum_client = EthereumClientProvider()
        chain_id = str(ethereum_client.get_chain_id())

        if not safe_version:
            addresses = get_deployment_addresses(safe_deployments, chain_id)
        elif safe_version in safe_deployments:
            addresses = get_deployment_addresses(
                safe_deployments[safe_version], chain_id
            )
        else:
            raise CommandError(
                f"Wrong Safe version {safe_version}, supported versions {safe_deployments.keys()}"
            )

        for contract_address in addresses:
            try:
                contract = Contract.objects.get(address=contract_address)
                # Remove previous one if exist
                contract.logo.delete(save=True)
                contract.logo.save(
                    f"{contract.address}.png", File(open(logo_path, "rb"))
                )
                contract.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Contract {contract_address} successfully updated"
                    )
                )
            except Contract.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"Contract {contract_address} does not exist on database"
                    )
                )
                continue
