from typing import Iterator

from django.core.management.base import BaseCommand

from safe_eth.eth import get_auto_ethereum_client

from ...models import EthereumTx


class Command(BaseCommand):
    help = "Fix EIP1559 transactions"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ethereum_client = get_auto_ethereum_client()

    def fix_ethereum_txs(self, ethereum_txs: Iterator[EthereumTx]):
        if ethereum_txs:
            txs = self.ethereum_client.get_transactions(
                [ethereum_tx.tx_hash for ethereum_tx in ethereum_txs]
            )
            for tx, ethereum_tx in zip(txs, ethereum_txs):
                if tx and "maxFeePerGas" in tx:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Fixing tx with tx-hash={ethereum_tx.tx_hash}"
                        )
                    )
                    ethereum_tx.max_fee_per_gas = tx.get("maxFeePerGas")
                    ethereum_tx.max_priority_fee_per_gas = tx.get(
                        "maxPriorityFeePerGas"
                    )
                    ethereum_tx.type = int(tx.get("type", "0x0"), 0)
                    ethereum_tx.save(
                        update_fields=[
                            "max_fee_per_gas",
                            "max_priority_fee_per_gas",
                            "type",
                        ]
                    )

    def handle(self, *args, **options):
        queryset = EthereumTx.objects.filter(type=0).order_by("-block_id")
        total = queryset.count()
        self.stdout.write(
            self.style.SUCCESS(f"Fixing ethereum txs. {total} remaining to be fixed")
        )
        ethereum_txs = []
        for i, ethereum_tx in enumerate(queryset.iterator()):
            ethereum_txs.append(ethereum_tx)
            if len(ethereum_txs) == 500:
                self.fix_ethereum_txs(ethereum_txs)
                ethereum_txs.clear()
                self.stdout.write(self.style.SUCCESS(f"Processing {i}/{total}"))

        self.fix_ethereum_txs(ethereum_txs)
