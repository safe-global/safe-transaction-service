from typing import Optional, Sequence

from django.core.management.base import BaseCommand

from eth_typing import ChecksumAddress
from safe_eth.eth.utils import fast_to_checksum_address

from safe_transaction_service.history.models import EthereumTx

from ...constants import USER_OPERATION_EVENT_TOPIC
from ...services import get_aa_processor_service
from ...utils import get_user_operation_sender_from_user_operation_log


class Command(BaseCommand):
    help = "Force reindexing of Safe events/traces (depending on the running mode)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--addresses",
            nargs="+",
            help="Safe addresses. If not provided all will be reindexed",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Reindexing ERC4337 UserOperations"))
        addresses = (
            [fast_to_checksum_address(address) for address in options["addresses"]]
            if options["addresses"]
            else None
        )

        processed_user_operations = self.reindex(addresses)
        self.stdout.write(
            self.style.SUCCESS(f"Reindexed {processed_user_operations} UserOperations")
        )

    def reindex(
        self,
        addresses: Optional[Sequence[ChecksumAddress]],
    ) -> None:
        topic = USER_OPERATION_EVENT_TOPIC.hex()
        aa_processor_service = get_aa_processor_service()
        processed_user_operations = 0
        for tx in EthereumTx.objects.account_abstraction_txs():
            for log in tx.logs:
                if log["topics"][0] == topic:
                    safe_address = get_user_operation_sender_from_user_operation_log(
                        log
                    )
                    if addresses and safe_address not in addresses:
                        continue
                    processed_user_operations += (
                        aa_processor_service.process_aa_transaction(safe_address, tx)
                    )
        return processed_user_operations
