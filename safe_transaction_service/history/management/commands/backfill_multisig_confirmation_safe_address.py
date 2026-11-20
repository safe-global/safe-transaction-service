import argparse
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import batched

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.utils import fast_to_checksum_address
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.util.util import to_0x_hex_str

from ...cache import CacheSafeTxsView, remove_cache_view_for_addresses
from ...models import InternalTxDecoded, MultisigConfirmation, MultisigTransaction

APPROVED_HASH = SafeSignatureType.APPROVED_HASH.value


def _positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} must be a positive integer")
    return ivalue


@dataclass
class ApprovalSafeAddresses:
    """
    Safe addresses found for the approvals stored without them
    """

    # Approvals with exactly one matching ``approveHash``
    safe_address_by_id: dict[int, ChecksumAddress] = field(default_factory=dict)
    # Bound approvals whose hash was approved on several Safes, none of them the
    # Safe of the transaction they are bound to
    bound_to_another_safe_ids: set[int] = field(default_factory=set)


class Command(BaseCommand):
    help = (
        "Set `safe_address` on the on-chain approval confirmations stored without it, "
        "using the Safe where `approveHash` was called. Then bind the approvals made "
        "on the Safe of an existing transaction, unbind the approvals bound to a "
        "transaction of another Safe, and untrust the pending transactions left with "
        "no confirmation"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report every change without writing anything",
        )
        parser.add_argument(
            "--batch-size",
            type=_positive_int,
            default=100,
            help="Confirmations processed per query",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        approval_safe_addresses = self.fill_safe_addresses(dry_run, batch_size)
        bound_safe_tx_hashes = self.bind_approvals_made_on_transaction_safe(
            approval_safe_addresses, dry_run, batch_size
        )
        # Unbinding and untrusting go together, so a failed run leaves the approvals
        # bound and running the command again untrusts the transactions
        with transaction.atomic():
            foreign_approval_ids_by_safe_tx_hash = (
                self.unbind_approvals_made_on_another_safe(
                    approval_safe_addresses, dry_run
                )
            )
            untrusted_count = self.untrust_transactions_without_confirmations(
                foreign_approval_ids_by_safe_tx_hash, bound_safe_tx_hashes, dry_run
            )

        summary_verb = "Would" if dry_run else "Did"
        self.stdout.write(
            self.style.SUCCESS(
                f"{summary_verb} set Safe address on "
                f"{len(approval_safe_addresses.safe_address_by_id)} confirmations, "
                f"bind {len(bound_safe_tx_hashes)} confirmations, unbind approvals "
                f"from {len(foreign_approval_ids_by_safe_tx_hash)} transactions and "
                f"untrust {untrusted_count} transactions"
            )
        )

    @staticmethod
    def _get_approve_hash_safes(
        ethereum_tx_ids: list[bytes],
    ) -> dict[tuple[HexBytes, HexBytes], list[tuple[ChecksumAddress | None, str]]]:
        """
        :return: ``(owner, Safe)`` of every ``approveHash`` call in the ethereum txs,
            by ``(ethereum tx hash, approved hash)``. Events (L2) carry the owner,
            traces (L1) do not, so it is ``None`` for them
        """
        approve_hash_safes = defaultdict(list)
        for ethereum_tx_id, safe_address, arguments in InternalTxDecoded.objects.filter(
            function_name="approveHash",
            internal_tx__ethereum_tx_id__in=ethereum_tx_ids,
        ).values_list("internal_tx__ethereum_tx_id", "internal_tx___from", "arguments"):
            decoded_owner = (
                fast_to_checksum_address(arguments["owner"])
                if "owner" in arguments
                else None
            )
            approve_hash_safes[
                (HexBytes(ethereum_tx_id), HexBytes(arguments["hashToApprove"]))
            ].append((decoded_owner, safe_address))
        return approve_hash_safes

    def fill_safe_addresses(
        self, dry_run: bool, batch_size: int
    ) -> ApprovalSafeAddresses:
        """
        :return: Safe addresses found for the approvals stored without them
        """
        approvals_without_safe_address = (
            MultisigConfirmation.objects.filter(
                safe_address=None, signature_type=APPROVED_HASH
            )
            .exclude(ethereum_tx=None)
            .order_by()
            .values_list(
                "id",
                "multisig_transaction_hash",
                "owner",
                "ethereum_tx_id",
                "multisig_transaction__safe",
            )
        )
        total = approvals_without_safe_address.count()
        self.stdout.write(
            self.style.SUCCESS(f"Found {total} approvals without Safe address")
        )

        approval_safe_addresses = ApprovalSafeAddresses()
        not_found = 0
        ambiguous = 0
        processed = 0
        for approval_batch in batched(
            approvals_without_safe_address.iterator(chunk_size=batch_size),
            batch_size,
            strict=False,
        ):
            approve_hash_safes = self._get_approve_hash_safes(
                [ethereum_tx_id for _, _, _, ethereum_tx_id, _ in approval_batch]
            )
            batch_safe_address_by_id = {}
            for (
                confirmation_id,
                approved_hash,
                owner,
                ethereum_tx_id,
                transaction_safe,
            ) in approval_batch:
                safe_addresses = {
                    safe_address
                    for decoded_owner, safe_address in approve_hash_safes[
                        (HexBytes(ethereum_tx_id), HexBytes(approved_hash))
                    ]
                    if decoded_owner in (None, owner)
                }
                if not safe_addresses:
                    not_found += 1
                elif len(safe_addresses) == 1:
                    batch_safe_address_by_id[confirmation_id] = safe_addresses.pop()
                else:
                    ambiguous += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping confirmation id={confirmation_id}, hash "
                            f"approved on several Safes {safe_addresses}"
                        )
                    )
                    if transaction_safe and transaction_safe not in safe_addresses:
                        approval_safe_addresses.bound_to_another_safe_ids.add(
                            confirmation_id
                        )

            if batch_safe_address_by_id and not dry_run:
                MultisigConfirmation.objects.bulk_update(
                    [
                        MultisigConfirmation(id=confirmation_id, safe_address=safe)
                        for confirmation_id, safe in batch_safe_address_by_id.items()
                    ],
                    ["safe_address"],
                )
            approval_safe_addresses.safe_address_by_id.update(batch_safe_address_by_id)
            processed += len(approval_batch)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Progress {processed}/{total} "
                    f"filled={len(approval_safe_addresses.safe_address_by_id)} "
                    f"not_found={not_found} ambiguous={ambiguous}"
                )
            )
        return approval_safe_addresses

    @staticmethod
    def _iterate_approvals_with_safe_address(
        approvals: QuerySet,
        approval_safe_addresses: ApprovalSafeAddresses,
        fields: list[str],
    ) -> Iterator[tuple]:
        """
        A dry run does not write the Safe addresses it finds, so they are taken from
        ``approval_safe_addresses`` when the stored one is empty

        :return: For each approval of ``approvals``: its id, its Safe address and the
            values of ``fields``
        """
        for confirmation_id, safe_address, *values in (
            approvals.order_by().values_list("id", "safe_address", *fields).iterator()
        ):
            yield (
                confirmation_id,
                safe_address
                or approval_safe_addresses.safe_address_by_id.get(confirmation_id),
                *values,
            )

    def bind_approvals_made_on_transaction_safe(
        self,
        approval_safe_addresses: ApprovalSafeAddresses,
        dry_run: bool,
        batch_size: int,
    ) -> set[HexBytes]:
        """
        Unbound approvals made on the Safe of an existing transaction are created
        again, so the post save signal binds them and the transaction becomes
        trusted, as for any new confirmation

        :return: Hashes of the transactions approvals were bound to
        """
        unbound_approvals = MultisigConfirmation.objects.without_transaction().filter(
            signature_type=APPROVED_HASH
        )
        bound_safe_tx_hashes = set()
        for approval_batch in batched(
            self._iterate_approvals_with_safe_address(
                unbound_approvals,
                approval_safe_addresses,
                ["multisig_transaction_hash"],
            ),
            batch_size,
            strict=False,
        ):
            transaction_safe_by_hash = {
                HexBytes(safe_tx_hash): safe
                for safe_tx_hash, safe in MultisigTransaction.objects.filter(
                    safe_tx_hash__in=[
                        safe_tx_hash for _, _, safe_tx_hash in approval_batch
                    ]
                ).values_list("safe_tx_hash", "safe")
            }
            for confirmation_id, safe_address, safe_tx_hash in approval_batch:
                safe_tx_hash = HexBytes(safe_tx_hash)
                if not safe_address or safe_address != transaction_safe_by_hash.get(
                    safe_tx_hash
                ):
                    continue
                if not dry_run and not self._create_approval_again(
                    confirmation_id, safe_address
                ):
                    continue
                bound_safe_tx_hashes.add(safe_tx_hash)
                self.stdout.write(
                    f"Binding confirmation id={confirmation_id} to "
                    f"safe-tx-hash={to_0x_hex_str(safe_tx_hash)}"
                )
        return bound_safe_tx_hashes

    @staticmethod
    def _create_approval_again(
        confirmation_id: int, safe_address: ChecksumAddress
    ) -> bool:
        """
        :return: ``False`` if the approval no longer exists, as the indexer can
            replace it while the command runs
        """
        with transaction.atomic():
            multisig_confirmation = MultisigConfirmation.objects.filter(
                pk=confirmation_id
            ).first()
            if not multisig_confirmation:
                return False
            multisig_confirmation.delete()
            multisig_confirmation.pk = None
            multisig_confirmation.safe_address = safe_address
            multisig_confirmation.save()
            # Binding sets `modified` to the approval block time, which can be old
            MultisigTransaction.objects.filter(
                pk=multisig_confirmation.multisig_transaction_hash
            ).update(modified=timezone.now())
        return True

    def unbind_approvals_made_on_another_safe(
        self, approval_safe_addresses: ApprovalSafeAddresses, dry_run: bool
    ) -> dict[HexBytes, list[int]]:
        """
        An approval made on another Safe is never valid for the transaction.
        Approvals whose Safe could not be found are kept bound and counted.

        :return: Ids of the unbound approvals, by hash of their transaction
        """
        bound_approvals = MultisigConfirmation.objects.with_transaction().filter(
            signature_type=APPROVED_HASH
        )
        foreign_approval_ids_by_safe_tx_hash = defaultdict(list)
        affected_safe_addresses = set()
        kept_without_safe_address = 0
        for (
            confirmation_id,
            safe_address,
            safe_tx_hash,
            transaction_safe,
            owner,
        ) in self._iterate_approvals_with_safe_address(
            bound_approvals,
            approval_safe_addresses,
            ["multisig_transaction_id", "multisig_transaction__safe", "owner"],
        ):
            is_made_on_another_safe = (
                confirmation_id in approval_safe_addresses.bound_to_another_safe_ids
                or (safe_address and safe_address != transaction_safe)
            )
            if not is_made_on_another_safe:
                if not safe_address:
                    kept_without_safe_address += 1
                continue
            foreign_approval_ids_by_safe_tx_hash[HexBytes(safe_tx_hash)].append(
                confirmation_id
            )
            affected_safe_addresses.add(transaction_safe)
            self.stdout.write(
                self.style.WARNING(
                    f"Unbinding approval id={confirmation_id} of owner={owner} "
                    f"made on Safe={safe_address or 'several Safes'} from "
                    f"safe-tx-hash={to_0x_hex_str(HexBytes(safe_tx_hash))} of "
                    f"Safe={transaction_safe}"
                )
            )
        self.stdout.write(
            f"Bound approvals kept without Safe address: {kept_without_safe_address}"
        )

        if foreign_approval_ids_by_safe_tx_hash and not dry_run:
            MultisigConfirmation.objects.filter(
                id__in=[
                    confirmation_id
                    for confirmation_ids in foreign_approval_ids_by_safe_tx_hash.values()
                    for confirmation_id in confirmation_ids
                ]
            ).update(multisig_transaction=None)
            remove_cache_view_for_addresses(
                CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY,
                list(affected_safe_addresses),
            )
        return foreign_approval_ids_by_safe_tx_hash

    def untrust_transactions_without_confirmations(
        self,
        foreign_approval_ids_by_safe_tx_hash: dict[HexBytes, list[int]],
        bound_safe_tx_hashes: set[HexBytes],
        dry_run: bool,
    ) -> int:
        """
        A pending transaction not proposed by a delegate, left with no confirmation
        once the approvals made on another Safe are unbound, was only trusted
        because of them. Transactions that got an approval bound in this run keep
        it, also in a dry run where the binding is not written.

        :return: Number of transactions untrusted
        """
        untrusted_transactions = [
            multisig_transaction
            for multisig_transaction in MultisigTransaction.objects.not_executed()
            .trusted()
            .filter(
                safe_tx_hash__in=foreign_approval_ids_by_safe_tx_hash,
                proposed_by_delegate=None,
            )
            if HexBytes(multisig_transaction.safe_tx_hash) not in bound_safe_tx_hashes
            and not multisig_transaction.confirmations.exclude(
                id__in=foreign_approval_ids_by_safe_tx_hash[
                    HexBytes(multisig_transaction.safe_tx_hash)
                ]
            ).exists()
        ]
        for multisig_transaction in untrusted_transactions:
            self.stdout.write(
                self.style.WARNING(
                    "Untrusting safe-tx-hash="
                    f"{to_0x_hex_str(HexBytes(multisig_transaction.safe_tx_hash))} "
                    f"Safe={multisig_transaction.safe} "
                    f"nonce={multisig_transaction.nonce} "
                    f"proposer={multisig_transaction.proposer} "
                    f"origin={multisig_transaction.origin}"
                )
            )

        if dry_run or not untrusted_transactions:
            return len(untrusted_transactions)

        # The service keeps adding confirmations while the command runs, so the
        # update checks again that no other confirmation exists when it writes
        foreign_approval_ids = [
            confirmation_id
            for confirmation_ids in foreign_approval_ids_by_safe_tx_hash.values()
            for confirmation_id in confirmation_ids
        ]
        untrusted_count = (
            MultisigTransaction.objects.filter(
                safe_tx_hash__in=[
                    multisig_transaction.safe_tx_hash
                    for multisig_transaction in untrusted_transactions
                ]
            )
            .exclude(
                Exists(
                    MultisigConfirmation.objects.filter(
                        multisig_transaction_id=OuterRef("safe_tx_hash")
                    ).exclude(id__in=foreign_approval_ids)
                )
            )
            .update(trusted=False)
        )
        if untrusted_count < len(untrusted_transactions):
            self.stdout.write(
                self.style.WARNING(
                    f"{len(untrusted_transactions) - untrusted_count} transactions "
                    "got a confirmation while running and stay trusted"
                )
            )
        remove_cache_view_for_addresses(
            CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY,
            list(
                {
                    multisig_transaction.safe
                    for multisig_transaction in untrusted_transactions
                }
            ),
        )
        return untrusted_count
