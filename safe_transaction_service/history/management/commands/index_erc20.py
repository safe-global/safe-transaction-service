from django.core.management.base import BaseCommand

from ...indexers import Erc20EventsIndexerProvider


class Command(BaseCommand):
    help = 'Force indexing of ERC20/721 if transfers are not updated for a Safe'

    def add_arguments(self, parser):
        parser.add_argument('addresses', nargs='+', help='Safe addresses')

    def handle(self, *args, **options):
        addresses = options['addresses']
        erc20_events_indexer = Erc20EventsIndexerProvider()
        updated = False
        while not updated:
            block_number = erc20_events_indexer.ethereum_client.current_block_number
            _, updated = erc20_events_indexer.process_addresses(addresses, block_number)
