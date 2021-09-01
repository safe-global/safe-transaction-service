from django.conf import settings
from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider

from ...indexers import (EthereumIndexer, InternalTxIndexerProvider,
                         SafeEventsIndexerProvider)


class Command(BaseCommand):
    help = 'Force reindexing of Safe events/traces (depending on the running mode)'

    def add_arguments(self, parser):
        parser.add_argument('--addresses', nargs='+', help='Safe addresses. If not provided all will be reindexed')
        parser.add_argument('--block-process-limit', type=int, help='Number of blocks to query each time',
                            default=1000)
        parser.add_argument('--from-block-number', type=int, help='Which block to start reindexing from', required=True)

    def handle(self, *args, **options):
        indexer_provider = SafeEventsIndexerProvider if settings.ETH_L2_NETWORK else InternalTxIndexerProvider
        indexer: EthereumIndexer = indexer_provider()
        ethereum_client = EthereumClientProvider()
        block_process_limit = options['block_process_limit']
        from_block_number = options['from_block_number']
        self.stdout.write(self.style.SUCCESS(f'Setting block-process-limit to {block_process_limit}'))
        self.stdout.write(self.style.SUCCESS(f'Setting from-block-number to {from_block_number}'))

        if options['addresses']:
            addresses = options['addresses']
            indexer.IGNORE_ADDRESSES_ON_LOG_FILTER = False  # Just process addresses provided
        else:
            addresses = list(indexer.database_queryset.values_list('address', flat=True))

        if not addresses:
            self.stdout.write(self.style.WARNING('No addresses to process'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Start reindexing addresses {addresses}'))
            current_block_number = ethereum_client.current_block_number
            block_number = from_block_number
            while block_number < current_block_number:
                elements = indexer.find_relevant_elements(addresses, block_number,
                                                          block_number + block_process_limit)
                indexer.process_elements(elements)
                block_number += block_process_limit
                self.stdout.write(self.style.SUCCESS(f'Current block number {block_number}, '
                                                     f'found {len(elements)} traces/events'))

            self.stdout.write(self.style.SUCCESS(f'End reindexing addresses {addresses}'))
