from django.conf import settings
from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_V1_3_0_contract

from ...models import MultisigTransaction, SafeLastStatus
from ...services import IndexServiceProvider


class Command(BaseCommand):
    help = "Check nonce calculated by the indexer is the same that blockchain nonce"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix", help="Fix nonce problems", action="store_true", default=False
        )

        parser.add_argument(
            "--force-batch-call",
            help="Force batch call instead of multicall for nonce recovery",
            action="store_true",
            default=False,
        )

    def get_nonce_fn(self, ethereum_client: EthereumClient):
        return get_safe_V1_3_0_contract(
            ethereum_client.w3, address=NULL_ADDRESS
        ).functions.nonce()

    def handle(self, *args, **options):
        fix = options["fix"]
        force_batch_call = options["force_batch_call"]

        queryset = SafeLastStatus.objects.all()
        if settings.ETH_L2_NETWORK:
            # Filter nonce=0 to exclude not initialized or non L2 Safes in a L2 network
            queryset = queryset.exclude(nonce=0)

        count = queryset.count()
        batch = 1000
        index_service = IndexServiceProvider()
        ethereum_client = index_service.ethereum_client
        nonce_fn = self.get_nonce_fn(ethereum_client)
        first_issue_block_number = ethereum_client.current_block_number
        all_addresses_to_reindex = set()

        for i in range(0, count, batch):
            self.stdout.write(self.style.SUCCESS(f"Processed {i}/{count}"))
            safe_statuses = queryset[i : i + batch]
            safe_statuses_list = list(safe_statuses)  # Force retrieve queryset from DB

            blockchain_nonces = ethereum_client.batch_call_same_function(
                nonce_fn,
                [safe_status.address for safe_status in safe_statuses_list],
                raise_exception=False,
                force_batch_call=force_batch_call,
            )

            addresses_to_reindex = set()
            for safe_status, blockchain_nonce in zip(
                safe_statuses_list, blockchain_nonces
            ):
                address = safe_status.address
                nonce = safe_status.nonce
                if safe_status.is_corrupted():
                    self.stdout.write(
                        self.style.WARNING(
                            f"Safe={address} is corrupted, has some old "
                            f"transactions missing"
                        )
                    )
                    addresses_to_reindex.add(address)

                if blockchain_nonce is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Safe={address} looks problematic, "
                            f"cannot retrieve blockchain-nonce"
                        )
                    )
                elif nonce != blockchain_nonce:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Safe={address} stored nonce={nonce} is "
                            f"different from blockchain-nonce={blockchain_nonce}"
                        )
                    )
                    if last_valid_transaction := MultisigTransaction.objects.last_valid_transaction(
                        address
                    ):
                        self.stdout.write(
                            self.style.WARNING(
                                f"Last valid transaction for Safe={address} has safe-nonce={last_valid_transaction.nonce} "
                                f"safe-transaction-hash={last_valid_transaction.safe_tx_hash} and "
                                f"ethereum-tx-hash={last_valid_transaction.ethereum_tx_id}"
                            )
                        )
                        first_issue_block_number = min(
                            last_valid_transaction.ethereum_tx.block_id,
                            first_issue_block_number,
                        )
                    addresses_to_reindex.add(address)

            if fix and addresses_to_reindex:
                all_addresses_to_reindex |= addresses_to_reindex
                self.stdout.write(
                    self.style.SUCCESS(f"Fixing Safes={addresses_to_reindex}")
                )
                index_service.reprocess_addresses(addresses_to_reindex)

        if all_addresses_to_reindex:
            self.stdout.write(
                self.style.SUCCESS(
                    f"First issue found on {first_issue_block_number} - Fixed Safes {all_addresses_to_reindex}"
                )
            )
