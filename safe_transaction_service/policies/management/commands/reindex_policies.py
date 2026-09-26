# SPDX-License-Identifier: FSL-1.1-MIT
from django.core.management.base import BaseCommand, CommandError

from ...models import SafePolicyGuard


class Command(BaseCommand):
    help = (
        "Rewind the indexing cursor of the monitored Safe Policy Guards, so the indexer "
        "scans their events again from the given block"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-block-number",
            type=int,
            help="Block to rewind the indexing cursor to",
            required=True,
        )
        parser.add_argument(
            "--addresses",
            nargs="+",
            help="Guard addresses. If not provided all the monitored guards are rewound",
        )

    def handle(self, *args, **options):
        from_block_number = options["from_block_number"]
        addresses = options["addresses"]
        if from_block_number < 0:
            raise CommandError("--from-block-number cannot be negative")

        queryset = SafePolicyGuard.objects.all()
        if addresses:
            queryset = queryset.filter(address__in=addresses)
            if queryset.count() != len(addresses):
                raise CommandError(
                    f"Not all the provided addresses are monitored guards: {addresses}"
                )

        # Events already indexed are not deleted, they are inserted ignoring conflicts on
        # `(ethereum_tx, log_index)`, so reindexing only fills the gaps
        updated = queryset.filter(tx_block_number__gt=from_block_number).update(
            tx_block_number=from_block_number
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Rewound {updated} guard(s) to block-number={from_block_number}"
            )
        )
