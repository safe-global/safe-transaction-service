# SPDX-License-Identifier: FSL-1.1-MIT
from django.core.management.base import BaseCommand

from safe_transaction_service.history.indexers.tx_processor import (
    SafeTxProcessorProvider,
)
from safe_transaction_service.history.models import MultisigTransaction


class Command(BaseCommand):
    help = "Backfill payment field for executed MultisigTransactions by reading ethereum_tx logs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--safe-address",
            type=str,
            help="Only process transactions for this Safe address",
        )

    def handle(self, *args, **options):
        safe_address = options["safe_address"]
        tx_processor = SafeTxProcessorProvider()

        queryset = (
            MultisigTransaction.objects.exclude(ethereum_tx=None)
            .filter(payment=None)
            .select_related("ethereum_tx")
        )
        if safe_address:
            queryset = queryset.filter(safe=safe_address)

        total = queryset.count()
        self.stdout.write(f"Processing {total} MultisigTransactions")

        updated = 0
        for i, multisig_tx in enumerate(queryset.iterator()):
            if i % 100 == 0:
                self.stdout.write(f"Progress {i}/{total}")
            _, payment = tx_processor.get_execution_result(
                multisig_tx.ethereum_tx, multisig_tx.safe_tx_hash
            )
            if payment is not None:
                multisig_tx.payment = payment
                multisig_tx.save(update_fields=["payment"])
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated payment for {updated}/{total} MultisigTransactions"
            )
        )
