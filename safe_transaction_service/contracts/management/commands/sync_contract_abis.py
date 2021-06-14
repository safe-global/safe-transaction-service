from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider

from ...models import Contract


class Command(BaseCommand):
    help = 'Sync contract names/ABIS scraping from etherscan/sourcify'

    def add_arguments(self, parser):
        parser.add_argument('--all', help="Sync contract names/ABIS for contracts already synced", action='store_true',
                            default=False)

    def handle(self, *args, **options):
        every_contract = options['all']

        ethereum_client = EthereumClientProvider()
        network = ethereum_client.get_network()

        contract_queryset = Contract.objects.all()
        if not every_contract:
            contract_queryset = contract_queryset.filter(contract_abi=None)

        for contract in contract_queryset:
            if contract.sync_abi_from_api(network=network):
                self.stdout.write(self.style.SUCCESS(f'Synced contract {contract.address} - {contract.name}'))
