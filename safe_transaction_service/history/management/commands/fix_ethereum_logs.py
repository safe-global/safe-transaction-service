from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider

from ...models import EthereumTx
from ...utils import clean_receipt_log


class Command(BaseCommand):
    help = 'Check all stored ethereum_txs have logs. Fixes them if no log found'

    def handle(self, *args, **options):
        ethereum_client = EthereumClientProvider()
        total = EthereumTx.objects.filter(logs=None).count()
        processed = 200
        self.stdout.write(self.style.SUCCESS(f'Fixing ethereum logs. {total} remaining to be fixed'))
        while True:
            ethereum_txs = EthereumTx.objects.filter(logs=None)[:processed]
            if not ethereum_txs:
                break

            tx_hashes = [ethereum_tx.tx_hash for ethereum_tx in ethereum_txs]
            tx_receipts = ethereum_client.get_transaction_receipts(tx_hashes)
            for ethereum_tx, tx_receipt in zip(ethereum_txs, tx_receipts):
                ethereum_tx.logs = [clean_receipt_log(log) for log in tx_receipt['logs']]
                ethereum_tx.save(update_fields=['logs'])
                total -= 1

            self.stdout.write(self.style.SUCCESS(f'Fixed {processed} ethereum logs. {total} remaining to be fixed'))
