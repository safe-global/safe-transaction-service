import json

from django.core.management.base import BaseCommand

from safe_transaction_service.contracts.tx_decoder import get_db_tx_decoder

from ...models import MultisigTransaction


class Command(BaseCommand):
    help = "Exports multisig tx data"

    def add_arguments(self, parser):
        parser.add_argument("--file-name", help="Filename", default="result.csv")

    def handle(self, *args, **options):
        file_name = options["file_name"]

        queryset = MultisigTransaction.objects.exclude(origin__exact={}).exclude(
            ethereum_tx=None
        )
        count = queryset.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Start exporting of {queryset.count()} "
                f"multisig tx data to {file_name}"
            )
        )
        if count:
            with open(file_name, "w") as f:
                decoder = get_db_tx_decoder()
                f.write(
                    "|".join(
                        [
                            "Execution date",
                            "tx-hash",
                            "safe-address",
                            "gas_price",
                            "gas_limit",
                            "gas_used",
                            "to",
                            "failed",
                            "origin",
                            "decodedData",
                        ]
                    )
                    + "\n"
                )
                for m in queryset.select_related("ethereum_tx__block"):
                    ethereum_tx = m.ethereum_tx
                    f.write(
                        "|".join(
                            [
                                str(m.execution_date),
                                m.ethereum_tx_id,
                                m.safe,
                                str(ethereum_tx.gas_price),
                                str(m.ethereum_tx.gas),
                                str(m.ethereum_tx.gas_used),
                                m.to,
                                str(m.failed),
                                m.origin,
                                json.dumps(decoder.get_data_decoded(m.data.tobytes()))
                                if m.data
                                else "",
                            ]
                        )
                        + "\n"
                    )
            self.stdout.write(
                self.style.SUCCESS(f"Multisig tx data was exported to {file_name}")
            )
