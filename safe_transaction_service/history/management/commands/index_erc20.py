from django.core.management.base import BaseCommand

from ...tasks import index_erc20_events_out_of_sync_task


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
        parser.add_argument(
            "--sync",
            help="Don't trigger an async task",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        addresses = options["addresses"]
        number_of_addresses = options["number_of_addresses"]
        sync = options["sync"]

        if block_process_limit := options["block_process_limit"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Setting block-process-limit to {block_process_limit}"
                )
            )
        if block_process_limit_max := options["block_process_limit_max"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Setting block-process-limit-max to {block_process_limit_max}"
                )
            )
        arguments = {
            "block_process_limit": block_process_limit,
            "block_process_limit_max": block_process_limit_max,
            "addresses": addresses,
            "number_of_addresses": number_of_addresses,
        }
        if sync:
            index_erc20_events_out_of_sync_task(**arguments)
        else:
            index_erc20_events_out_of_sync_task.delay(**arguments)
