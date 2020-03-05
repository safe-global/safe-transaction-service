from django.core.management.base import BaseCommand
from django.db.models import Q

from ...models import EthereumTx
from ...services import IndexServiceProvider


class Command(BaseCommand):
    help = 'Check all stored ethereum_txs have a valid receipt and block. Fixes them if a problem is found'

    def handle(self, *args, **options):
        queryset = EthereumTx.objects.filter(Q(block=None) | Q(gas_used=None))
        total = queryset.count()
        self.stdout.write(self.style.SUCCESS(f'Fixing ethereum txs. {total} remaining to be fixed'))
        index_service = IndexServiceProvider()
        ethereum_client = index_service.ethereum_client
        for i, ethereum_tx in enumerate(queryset.iterator()):
            tx_receipt = ethereum_client.get_transaction_receipt(ethereum_tx.tx_hash)
            block_number = tx_receipt['blockNumber']
            block = ethereum_tx.block or index_service.block_get_or_create_from_block_number(block_number)
            ethereum_tx.update_with_block_and_receipt(block, tx_receipt)
            self.stdout.write(self.style.SUCCESS(f'Processing {i}/{total} with tx-hash={ethereum_tx.tx_hash}'))

        self.stdout.write(self.style.SUCCESS(f'End fixing txs. {total} have been fixed'))
