from collections.abc import Sequence

from django.core.management.base import BaseCommand, CommandError

from eth_typing import ChecksumAddress

from ...models import SafeContract
from ...services import IndexServiceProvider


class Command(BaseCommand):
    help = "Force reindexing of Safe events/traces (depending on the running mode)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--addresses",
            nargs="+",
            help="Safe addresses. If not provided all will be reindexed",
        )
        parser.add_argument(
            "--block-process-limit",
            type=int,
            help="Number of blocks to query each time",
            default=100,
        )
        parser.add_argument(
            "--from-block-number",
            type=int,
            help="Which block to start reindexing from. If not provided, minimum creation block for provided addresses will be used, 0 otherwise",
            required=False,
        )

    def handle(self, *args, **options):
        block_process_limit = options["block_process_limit"]
        from_block_number = options["from_block_number"]
        addresses = options["addresses"]
        if addresses and not from_block_number:
            from_block_number = SafeContract.objects.get_minimum_creation_block_number(
                addresses
            )
            if from_block_number is None:
                raise CommandError(
                    "Cannot get from-block-number, please set --from-block-number yourself"
                )
            self.stdout.write(
                self.style.SUCCESS(f"Setting from-block-number to {from_block_number}")
            )
        elif not from_block_number:
            raise CommandError(
                "--from-block-number must be set if --addresses are not provided"
            )

        self.stdout.write(
            self.style.SUCCESS(f"Setting block-process-limit to {block_process_limit}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Setting from-block-number to {from_block_number}")
        )

        self.reindex(from_block_number, block_process_limit, addresses)

    def reindex(
        self,
        from_block_number: int,
        block_process_limit: int | None,
        addresses: Sequence[ChecksumAddress] | None,
    ) -> None:
        index_service = IndexServiceProvider()
        # Reindex missing transactions
        result = index_service.reindex_master_copies(
            from_block_number,
            block_process_limit=block_process_limit,
            addresses=addresses,
        )
        # Reprocess addresses again (if provided)
        if addresses:
            index_service.reprocess_addresses(addresses)
        return result
