import time

from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider

from safe_transaction_service.tokens.clients import EtherscanScraper
from safe_transaction_service.tokens.clients.etherscan_scraper import \
    EtherscanScraperException

from ...models import Contract, ContractAbi


class Command(BaseCommand):
    help = 'Sync contract names/ABIS scraping from etherscan/sourcify'

    def add_arguments(self, parser):
        parser.add_argument('--all', help="Sync contract names/ABIS for contracts already synced", action='store_true',
                            default=False)
        parser.add_argument('--scraper', help="Scrape etherscan instead of using API (to have names)",
                            action='store_true', default=False)

    def handle(self, *args, **options):
        every_contract = options['all']
        scraper = options['scraper']
        etherscan_client = EtherscanScraper() if scraper else None

        ethereum_client = EthereumClientProvider()
        network = ethereum_client.get_network()

        contract_queryset = Contract.objects.all()
        if not every_contract:
            contract_queryset = contract_queryset.filter(contract_abi=None)

        for contract in contract_queryset:
            updated = False
            if not etherscan_client:
                updated = contract.sync_abi_from_api(network=network)
            else:  # Use etherscan scraper
                try:
                    contract_info = etherscan_client.get_contract_info(contract.address)
                    if contract_info:
                        contract_abi, _ = ContractAbi.objects.update_or_create(abi=contract_info.abi,
                                                                               defaults={
                                                                                   'description': contract_info.name
                                                                               })
                        contract, _ = Contract.objects.update_or_create(address=contract_info.abi,
                                                                        defaults={
                                                                            'name': contract_info.name,
                                                                            'abi': contract_abi
                                                                        })
                        updated = True
                except EtherscanScraperException:
                    time.sleep(5)

            if updated:
                self.stdout.write(self.style.SUCCESS(f'Synced contract {contract.address} - {contract.name}'))
