# SPDX-License-Identifier: FSL-1.1-MIT
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

try:
    from safe_eth.eth import EthereumClientProvider
except ImportError:  # pragma: no cover - fallback for environments without provider
    from safe_eth.eth import get_auto_ethereum_client

    def EthereumClientProvider():
        return get_auto_ethereum_client()


from ...models import EthereumTx


class Command(BaseCommand):
    help = (
        "Delete recent EthereumTx rows marked successful in DB after confirming "
        "failed receipts on RPC"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Only inspect EthereumTx created in the last N days (default: all)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report rows that would be deleted",
        )
        parser.add_argument(
            "--retries",
            type=int,
            default=3,
            help="Number of RPC attempts per transaction before skipping",
        )
        parser.add_argument(
            "--backoff",
            type=float,
            default=2.0,
            help="Base backoff in seconds between retries (exponential: backoff ** attempt)",
        )

    def _get_receipt_with_retry(self, ethereum_client, tx_hash, retries, backoff):
        for attempt in range(retries):
            try:
                return ethereum_client.get_transaction_receipt(tx_hash)
            except Exception as exc:
                if attempt == retries - 1:
                    raise
                delay = backoff**attempt
                self.stdout.write(
                    self.style.WARNING(
                        f"RPC error for {tx_hash} (attempt {attempt + 1}/{retries}): {exc}. "
                        f"Retrying in {delay}s..."
                    )
                )
                time.sleep(delay)

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        retries = options["retries"]
        backoff = options["backoff"]
        ethereum_client = EthereumClientProvider()

        queryset = EthereumTx.objects.filter(status=1).only("tx_hash")
        if days is not None:
            cutoff = timezone.now() - timedelta(days=days)
            queryset = queryset.filter(created__gte=cutoff)
            scope_msg = f"created since {cutoff.isoformat()}"
        else:
            scope_msg = "all time"

        total = queryset.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Checking {total} EthereumTx rows with status=1 ({scope_msg})"
            )
        )

        checked = 0
        deleted = 0
        missing_receipts = 0
        still_success = 0
        rpc_errors = 0

        for i, ethereum_tx in enumerate(queryset.iterator(), start=1):
            if i % 100_000 == 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Progress {i}/{total} checked={checked} deleted={deleted}"
                    )
                )

            try:
                tx_receipt = self._get_receipt_with_retry(
                    ethereum_client, ethereum_tx.tx_hash, retries, backoff
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"Skipping {ethereum_tx.tx_hash} after {retries} failed attempts: {exc}"
                    )
                )
                rpc_errors += 1
                continue
            checked += 1

            if not tx_receipt:
                missing_receipts += 1
                continue

            if tx_receipt.get("status") == 0:
                self.stdout.write(f"Deleting {ethereum_tx.tx_hash}")
                if not dry_run:
                    ethereum_tx.delete()
                deleted += 1
            else:
                still_success += 1

        action = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {deleted}/{total} EthereumTx rows. "
                f"Checked={checked}, missing_receipts={missing_receipts}, "
                f"still_success={still_success}, rpc_errors={rpc_errors}"
            )
        )
