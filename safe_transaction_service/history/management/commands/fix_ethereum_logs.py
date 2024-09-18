from django.core.management.base import BaseCommand

from safe_eth.eth import get_auto_ethereum_client

from ...models import EthereumTx
from ...utils import clean_receipt_log


class Command(BaseCommand):
    help = "Add missing address to every EthereumTx log"

    def handle(self, *args, **options):
        # We need to add `address` to the logs, so we exclude empty logs and logs already containing `address`
        ethereum_client = get_auto_ethereum_client()
        queryset = EthereumTx.objects.exclude(logs__0__has_key="address").exclude(
            logs=[]
        )
        total = queryset.count()
        processed = 200
        self.stdout.write(
            self.style.SUCCESS(f"Fixing ethereum logs. {total} remaining to be fixed")
        )
        while True:
            ethereum_txs = queryset[:processed]
            if not ethereum_txs:
                break

            tx_hashes = [ethereum_tx.tx_hash for ethereum_tx in ethereum_txs]
            try:
                tx_receipts = ethereum_client.get_transaction_receipts(tx_hashes)
                for ethereum_tx, tx_receipt in zip(ethereum_txs, tx_receipts):
                    ethereum_tx.logs = [
                        clean_receipt_log(log) for log in tx_receipt["logs"]
                    ]
                    ethereum_tx.save(update_fields=["logs"])
                    total -= 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Fixed {processed} ethereum logs. {total} remaining to be fixed"
                    )
                )
            except IOError:
                self.stdout.write(
                    self.style.WARNING(
                        "Node connection error when retrieving tx receipts"
                    )
                )
        self.stdout.write(
            self.style.SUCCESS(f"End fixing txs. {total} have been fixed")
        )
