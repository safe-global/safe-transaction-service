from django.core.management.base import BaseCommand

from ...indexers import Erc20EventsIndexerProvider, FindRelevantElementsException


class Command(BaseCommand):
    help = "Force indexing of ERC20/721 if transfers are not updated for a Safe"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--addresses", nargs="+", help="Safe addresses")
        group.add_argument(
            "--number-of-addresses",
            type=int,
            help="Number of not updated addresses to process",
            default=100,
        )

        parser.add_argument(
            "--block-process-limit",
            type=int,
            help="Number of blocks to query each time",
            default=None,
        )
        parser.add_argument(
            "--block-process-limit-max",
            type=int,
            help="Max number of blocks to query each time",
            default=None,
        )

    def handle(self, *args, **options):
        erc20_events_indexer = Erc20EventsIndexerProvider()
        if block_process_limit := options["block_process_limit"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Setting block-process-limit to {block_process_limit}"
                )
            )
            erc20_events_indexer.block_process_limit = block_process_limit
        if block_process_limit_max := options["block_process_limit_max"]:
            erc20_events_indexer.block_process_limit_max = block_process_limit_max
            self.stdout.write(
                self.style.SUCCESS(
                    f"Setting block-process-limit-max to {block_process_limit_max}"
                )
            )

        current_block_number = erc20_events_indexer.ethereum_client.current_block_number
        addresses = options["addresses"] or [
            x.address
            for x in erc20_events_indexer.get_not_updated_addresses(
                current_block_number
            )[: options["number_of_addresses"]]
        ]

        if not addresses:
            self.stdout.write(self.style.WARNING("No addresses to process"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Start indexing ERC20 addresses {addresses}")
            )
            updated = False
            while not updated:
                try:
                    _, updated = erc20_events_indexer.process_addresses(
                        addresses, current_block_number
                    )
                except FindRelevantElementsException:
                    pass

            self.stdout.write(
                self.style.SUCCESS(f"End indexing ERC20 addresses {addresses}")
            )
