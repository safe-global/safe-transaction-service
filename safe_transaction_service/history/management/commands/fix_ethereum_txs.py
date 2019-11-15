from django.core.management.base import BaseCommand
from django.db.models import Q

from gnosis.eth import EthereumClientProvider

from ...models import EthereumBlock, EthereumTx


class Command(BaseCommand):
    help = 'Check all stored ethereum_txs have a valid receipt and block. Fixes them if a problem is found'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Fixing ethereum_txs'))
        queryset = EthereumTx.objects.filter(Q(block=None) | Q(gas_used=None))
        found = 0
        total = queryset.count()
        ethereum_client = EthereumClientProvider()
        for i, ethereum_tx in enumerate(queryset.iterator()):
            tx_receipt = ethereum_client.get_transaction_receipt(ethereum_tx.tx_hash)
            if not ethereum_tx.block:
                ethereum_tx.block = EthereumBlock.objects.get_or_create_from_block_number(tx_receipt['blockNumber'])

            ethereum_tx.gas_used = tx_receipt['gasUsed']
            ethereum_tx.status = tx_receipt.get('status')
            ethereum_tx.transaction_index = tx_receipt['transactionIndex']
            ethereum_tx.save(update_fields=['block', 'gas_used', 'status', 'transaction_index'])
            if i % 50 == 0:
                self.stdout.write(self.style.SUCCESS(f'Processing {i}/{total}'))
        self.stdout.write(self.style.SUCCESS(f'End checking txs. {found} have been fixed'))
