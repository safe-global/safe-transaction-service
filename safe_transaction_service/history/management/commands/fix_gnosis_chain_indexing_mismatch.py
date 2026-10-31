# SPDX-License-Identifier: FSL-1.1-MIT
"""
Repair data indexed from a tracing node that returned incomplete data for a
block range: receipts without logs, traces missing and traces stored under a
wrong ``traceAddress``. As the Safe nonce of a traced execution is counted from
the processed executions, those errors left Safes with wrong nonces,
``MultisigTransaction`` rows with wrong ``safe_tx_hash`` and correct hashes linked
to the wrong tx.

Steps, every one only touches rows that are still wrong, so the command can be run
again:

1. Fetch the receipt again for ``EthereumTx`` rows with no logs, store the logs and
   recalculate ``failed``/``payment`` of the multisig txs and ``failed`` of the
   module txs of those txs, the only fields built from logs.
2. Compare the Safe events of the range (executions, module executions and
   ``SafeSetup``) with the decoded traces of their txs. The traces of the txs that
   do not match are synced with ``trace_transaction``: the stored traces that are
   not on chain are deleted and the missing ones are indexed. The workers process
   the new traces and process the Safe again from them.
3. Fix the affected Safes: delete the executed ``MultisigTransaction`` rows whose
   hash is not in the execution logs of their tx (or unlink them if they were
   proposed by a user), and mark the Safe to be processed again by the workers
   from the first wrong row.

The point to process a Safe again from comes from its own rows, not from the block
range, so damage outside the range is also fixed.
"""

import dataclasses
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime
from enum import StrEnum
from functools import cached_property
from typing import Any, cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.db.models import Count, F, Func, IntegerField, Q

from eth_typing import ChecksumAddress, HexStr
from eth_utils import event_abi_to_log_topic
from hexbytes import HexBytes
from redis.exceptions import LockError
from redis.lock import Lock
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.eth.contracts import (
    get_safe_V1_3_0_contract,
    get_safe_V1_4_1_contract,
    get_safe_V1_5_0_contract,
)
from safe_eth.eth.utils import fast_to_checksum_address
from safe_eth.util.util import to_0x_hex_str
from web3 import Web3
from web3.types import FilterTrace, TxReceipt

from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.tasks import LOCK_TIMEOUT, get_task_lock_name
from safe_transaction_service.utils.utils import chunks

from ...cache import CacheSafeTxsView, remove_cache_view_for_addresses
from ...indexers import InternalTxIndexer, InternalTxIndexerProvider
from ...indexers.tx_processor import SafeTxProcessor, SafeTxProcessorProvider
from ...models import (
    EthereumTx,
    InternalTx,
    InternalTxDecoded,
    ModuleTransaction,
    MultisigTransaction,
    SafeContract,
    SafeLastStatus,
    SafeStatus,
)
from ...services import IndexServiceProvider
from ...tasks import process_decoded_internal_txs_for_safe_task
from ...utils import clean_receipt_log
from .safe_contract import _checksum_address


class SafeAction(StrEnum):
    """
    What is done with a Safe
    """

    OK = "ok"  # Nothing to fix
    RESET = "reset"  # Process again from the first wrong multisig tx
    SKIP_BANNED = "skip-banned"


@dataclasses.dataclass
class SafeRepair:
    """
    Result of checking a Safe against the logs
    """

    address: ChecksumAddress
    action: SafeAction
    # First block and its time to process the Safe again from
    from_block: int | None = None
    from_timestamp: datetime | None = None
    to_delete: list[HexStr] = dataclasses.field(default_factory=list)
    to_unlink: list[HexStr] = dataclasses.field(default_factory=list)


# Fields that identify a trace. The gas is left out, as nodes of different clients
# can report a different gas for the same trace
TRACE_KEY_FIELDS = (
    "trace_address",
    "_from",
    "to",
    "data",
    "value",
    "call_type",
    "tx_type",
)

# Gnosis Chain blocks indexed from the bad node. Receipts without logs go from
# block 41,454,189 (2025-08-05 16:14 UTC) to block 42,531,904 (2025-10-09 07:27 UTC).
# The defaults add about one day of margin on each side
DEFAULT_FROM_BLOCK = 41_437_000
DEFAULT_TO_BLOCK = 42_549_000

# Decoded functions of a Safe singleton and the kind of Safe event each one emits
FUNCTION_EVENTS = {
    "execTransaction": "execution",
    "execTransactionFromModule": "module-execution",
    "execTransactionFromModuleReturnData": "module-execution",
    "setup": "setup",
}
_SAFE_CONTRACTS = (
    get_safe_V1_3_0_contract(Web3()),
    get_safe_V1_4_1_contract(Web3()),
    get_safe_V1_5_0_contract(Web3()),
)
MODULE_EXECUTION_TOPICS = {
    event_abi_to_log_topic(event().abi)
    for contract in _SAFE_CONTRACTS
    for event in (
        contract.events.ExecutionFromModuleSuccess,
        contract.events.ExecutionFromModuleFailure,
    )
}
SETUP_TOPICS = {
    event_abi_to_log_topic(contract.events.SafeSetup().abi)
    for contract in _SAFE_CONTRACTS
}

# An empty `logs` array takes a few bytes. Filtering by size first avoids reading
# the logs of every tx of the range from TOAST
EMPTY_LOGS_MAX_SIZE = 64
RPC_BATCH_SIZE = 100  # Elements per RPC batch request
LOGS_BLOCK_WINDOW = 1_000  # Blocks whose Safe events are read at a time
PROGRESS_EVERY = 100
ITERATOR_CHUNK_SIZE = 2_000  # Rows read at a time when streaming
# Rows per statement when cleaning a Safe. Big Safes have millions of rows, so they
# are changed in short statements that do not block the workers for long
DB_BATCH_SIZE = 5_000
# Expiration of the per Safe processing lock while a Safe is cleaned. It is renewed
# before every batch, the expiration only frees the Safe if the command is killed
SAFE_LOCK_TIMEOUT = 30 * 60


class Command(BaseCommand):
    help = (
        "Repair txs, traces and Safe multisig txs indexed from a node that returned "
        "incomplete data in a block range"
    )

    def add_arguments(self, parser: CommandParser):
        parser.add_argument(
            "--from-block",
            type=int,
            default=DEFAULT_FROM_BLOCK,
            help=f"First block of the range (default: {DEFAULT_FROM_BLOCK})",
        )
        parser.add_argument(
            "--to-block",
            type=int,
            default=DEFAULT_TO_BLOCK,
            help=f"Last block of the range (default: {DEFAULT_TO_BLOCK})",
        )
        parser.add_argument(
            "--only-fix-safes",
            action="store_true",
            help="Only fix the Safes, to fix them in waves after the data of the "
            "range was repaired",
        )
        parser.add_argument(
            "--addresses",
            nargs="+",
            type=_checksum_address,
            help="Safes to fix. If not provided, the Safes with repeated executed "
            "nonces, the Safes with wrong multisig txs in the range and the Safes "
            "changed by the repair steps",
        )
        parser.add_argument(
            "--max-safes",
            type=int,
            default=None,
            help="Max number of Safes changed in this run, to fix them in waves. The "
            "wrong rows of a fixed Safe are deleted, so the next run continues with "
            "the rest",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report what would be changed",
        )

    def handle(self, *args, **options):
        self.setup(**options)
        if not options["only_fix_safes"]:
            self.fix_empty_logs()
            self.sync_mismatched_traces()
        self.fix_safes(options["addresses"])

    def setup(
        self,
        from_block: int = DEFAULT_FROM_BLOCK,
        to_block: int = DEFAULT_TO_BLOCK,
        max_safes: int | None = None,
        dry_run: bool = False,
        **kwargs,
    ) -> None:
        """
        Prepare the command to run its steps

        :raises CommandError: If the block range is not valid
        """
        if from_block > to_block:
            raise CommandError("--from-block must be lower or equal than --to-block")
        self.from_block = from_block
        self.to_block = to_block
        self.max_safes = max_safes
        self.dry_run = dry_run

        # The service timeouts protect the API from slow queries and lock queues.
        # This command scans millions of rows and waits on rows the workers lock,
        # so the timeouts are disabled for its own database session
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = 0")
            cursor.execute("SET lock_timeout = 0")

        self.ethereum_client = get_auto_ethereum_client()
        # Safes whose processed data changed in the repair steps, always checked
        # against the logs when fixing the Safes
        self.safes_to_fix: set[ChecksumAddress] = set()

        if self.dry_run:
            self.stdout.write(self.style.WARNING("Dry run, nothing will be changed"))
        self.stdout.write(f"Range: blocks {self.from_block}-{self.to_block}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @cached_property
    def tracing_indexer(self) -> InternalTxIndexer:
        """
        :return: A new indexer instance, so its already-processed cache does not
            interfere with the one of the running indexer
        """
        if not settings.ETHEREUM_TRACING_NODE_URL:
            raise CommandError("ETHEREUM_TRACING_NODE_URL is required")
        return InternalTxIndexerProvider.get_new_instance()

    @cached_property
    def master_copies(self) -> set[ChecksumAddress]:
        """
        :return: Monitored Safe singletons
        """
        return self.tracing_indexer._get_master_copy_addresses()

    @cached_property
    def tx_processor(self) -> SafeTxProcessor:
        return cast(SafeTxProcessor, SafeTxProcessorProvider())

    @cached_property
    def event_kinds(self) -> dict[bytes, str]:
        """
        :return: Kind of Safe event, as in ``FUNCTION_EVENTS``, by ``topic0`` of every
            Safe event version
        """
        return {
            **dict.fromkeys(
                self.tx_processor.safe_tx_execution_events_topics, "execution"
            ),
            **dict.fromkeys(MODULE_EXECUTION_TOPICS, "module-execution"),
            **dict.fromkeys(SETUP_TOPICS, "setup"),
        }

    @cached_property
    def banned_safes(self) -> set[ChecksumAddress]:
        """
        :return: Banned Safes, they are not fixed
        """
        return set(SafeContract.objects.get_banned_addresses())

    @cached_property
    def safes_with_repeated_executed_nonces(self) -> set[ChecksumAddress]:
        """
        :return: Safes with more than one executed ``MultisigTransaction`` for the same
            nonce. A nonce is executed once on chain, so these Safes were processed
            with a wrong nonce
        """
        self.stdout.write("Looking for Safes with repeated executed nonces")
        return {
            row["safe"]
            for row in MultisigTransaction.objects.executed()
            .values("safe", "nonce")
            .annotate(repeated=Count("safe_tx_hash"))
            .filter(repeated__gt=1)
            .order_by()
        }

    @cached_property
    def safes_with_wrong_executions_in_range(self) -> set[ChecksumAddress]:
        """
        :return: Safes with an executed ``MultisigTransaction`` in the range whose hash
            is not in the execution logs of its tx
        """
        self.stdout.write("Looking for Safes with wrong executions in the range")
        safes: set[ChecksumAddress] = set()
        # A short query per window of blocks, so no snapshot is kept open for the
        # whole range
        for window_from in range(self.from_block, self.to_block + 1, LOGS_BLOCK_WINDOW):
            for safe, safe_tx_hash, logs in (
                MultisigTransaction.objects.executed()
                .filter(
                    ethereum_tx__block_id__gte=window_from,
                    ethereum_tx__block_id__lte=min(
                        window_from + LOGS_BLOCK_WINDOW - 1, self.to_block
                    ),
                )
                .values_list("safe", "safe_tx_hash", "ethereum_tx__logs")
            ):
                if (
                    safe not in safes
                    and self._is_right_execution(logs, safe, safe_tx_hash) is False
                ):
                    safes.add(safe)
        return safes

    def _add_safes_to_fix(self, safes: Iterable[ChecksumAddress]) -> None:
        """
        Mark the Safes to be fixed. Every new Safe is printed when it is found, so the
        list is not lost if the command fails before fixing the Safes

        :param safes:
        """
        for safe in sorted(set(safes) - self.safes_to_fix):
            self.stdout.write(f"Safe to fix: {safe}")
            self.safes_to_fix.add(safe)

    @staticmethod
    def _remove_cached_views(safes: Iterable[ChecksumAddress]) -> None:
        """
        Remove the cached views of multisig and module txs of the Safes, needed when
        their rows are changed without Django signals

        :param safes:
        """
        if safes := list(safes):
            for cache_tag in (
                CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY,
                CacheSafeTxsView.LIST_MODULETRANSACTIONS_VIEW_CACHE_KEY,
            ):
                remove_cache_view_for_addresses(cache_tag, safes)

    def _progress(self, current: int, total: int, label: str) -> None:
        """
        Print progress every ``PROGRESS_EVERY`` elements

        :param current: Elements processed
        :param total: Elements to process
        :param label: Text printed before the counter
        """
        if current % PROGRESS_EVERY == 0:
            self.stdout.write(f"{label} {current}/{total}")

    def _is_right_execution(
        self,
        logs: list[dict[str, Any]] | None,
        safe_address: ChecksumAddress,
        safe_tx_hash: HexStr,
    ) -> bool | None:
        """
        The ``safe_tx_hash`` of an ``ExecutionSuccess``/``ExecutionFailure`` is
        ``topics[1]`` from v1.4.1 and the first 32 bytes of ``data`` before, as in
        ``SafeTxProcessor.get_execution_result``

        :param logs: Logs of the tx of an executed multisig tx, as stored in
            ``EthereumTx.logs``
        :param safe_address:
        :param safe_tx_hash:
        :return: ``True`` if ``safe_tx_hash`` is one of the executions of the Safe in
            the tx, ``False`` if it is not, ``None`` if the tx has no executions of
            the Safe and it cannot be checked
        """
        execution_topics = self.tx_processor.safe_tx_execution_events_topics
        executed_hashes: set[bytes] = set()
        for log in logs or []:
            topics = log["topics"]
            if (
                not topics
                or HexBytes(topics[0]) not in execution_topics
                or log["address"].lower() != safe_address.lower()
            ):
                continue
            if len(topics) == 2:
                executed_hashes.add(bytes(HexBytes(topics[1])))
            else:
                executed_hashes.add(bytes(HexBytes(log["data"])[:32]))
        if not executed_hashes:
            return None
        return bytes(HexBytes(safe_tx_hash)) in executed_hashes

    # ------------------------------------------------------------------
    # Step 1: empty logs
    # ------------------------------------------------------------------
    def _update_execution_results(
        self, ethereum_txs: dict[HexStr, EthereumTx]
    ) -> tuple[int, int]:
        """
        Recalculate the fields built from the logs: ``failed`` and ``payment`` of the
        multisig txs and ``failed`` of the module txs of the provided txs

        :param ethereum_txs: Txs with the new logs, by tx hash
        :return: Number of multisig txs and module txs changed
        """
        multisig_txs = []
        changed_safes: set[ChecksumAddress] = set()
        for multisig_tx in MultisigTransaction.objects.filter(
            ethereum_tx__in=list(ethereum_txs)
        ).only("safe_tx_hash", "safe", "ethereum_tx", "failed", "payment"):
            ethereum_tx = ethereum_txs[multisig_tx.ethereum_tx_id]
            result = self.tx_processor.get_execution_result(
                ethereum_tx, multisig_tx.safe_tx_hash
            )
            if result != (multisig_tx.failed, multisig_tx.payment):
                multisig_tx.failed, multisig_tx.payment = result
                multisig_txs.append(multisig_tx)
                changed_safes.add(multisig_tx.safe)

        module_txs = []
        for (
            internal_tx_id,
            tx_hash,
            module,
            safe,
            failed,
        ) in ModuleTransaction.objects.filter(
            internal_tx__ethereum_tx__in=list(ethereum_txs)
        ).values_list(
            "internal_tx_id", "internal_tx__ethereum_tx", "module", "safe", "failed"
        ):
            is_failed = self.tx_processor.is_module_failed(
                ethereum_txs[tx_hash], module, safe
            )
            if is_failed != failed:
                module_txs.append(
                    ModuleTransaction(internal_tx_id=internal_tx_id, failed=is_failed)
                )
                changed_safes.add(safe)

        # `bulk_update` does not change `modified` or send signals, so no events are
        # sent for these old txs and the cached views of the Safes are removed here
        if not self.dry_run:
            MultisigTransaction.objects.bulk_update(multisig_txs, ["failed", "payment"])
            ModuleTransaction.objects.bulk_update(module_txs, ["failed"])
            self._remove_cached_views(changed_safes)
        return len(multisig_txs), len(module_txs)

    def fix_empty_logs(self) -> None:
        """
        The bad node returned receipts without logs, so the receipt of every tx
        without logs is fetched again. A tx can also have no logs on chain (e.g.
        old Safe versions emit no events), those are left as they are.

        Logs are only used for ``failed`` and ``payment``, so those fields are
        recalculated and the Safes do not need to be processed again.
        """
        self.stdout.write(self.style.MIGRATE_HEADING("Fixing txs without logs"))
        tx_hashes = list(
            EthereumTx.objects.filter(
                block_id__gte=self.from_block, block_id__lte=self.to_block
            )
            .alias(
                logs_size=Func(
                    F("logs"), function="pg_column_size", output_field=IntegerField()
                )
            )
            .filter(
                Q(logs__isnull=True) | Q(logs_size__lt=EMPTY_LOGS_MAX_SIZE, logs__len=0)
            )
            .order_by("block_id")
            .values_list("tx_hash", flat=True)
        )
        total = len(tx_hashes)
        self.stdout.write(f"Found {total} txs without logs")
        counters = Counter[str]()
        checked = 0
        for tx_hashes_chunk in chunks(tx_hashes, RPC_BATCH_SIZE):
            receipts = self.ethereum_client.get_transaction_receipts(tx_hashes_chunk)
            updated: dict[HexStr, EthereumTx] = {}
            for tx_hash, receipt in zip(tx_hashes_chunk, receipts, strict=True):
                checked += 1
                self._progress(checked, total, "Checked receipts")
                if logs := [
                    clean_receipt_log(log) for log in cast(TxReceipt, receipt)["logs"]
                ]:
                    updated[tx_hash] = EthereumTx(tx_hash=tx_hash, logs=logs)
                else:
                    counters["still_empty"] += 1
            counters["updated"] += len(updated)

            multisig_changed, module_changed = self._update_execution_results(updated)
            counters["multisig_txs_changed"] += multisig_changed
            counters["module_txs_changed"] += module_changed
            if not self.dry_run:
                EthereumTx.objects.bulk_update(updated.values(), ["logs"])

        action = "Would update" if self.dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} logs of {counters['updated']}/{total} txs. "
                f"still_empty={counters['still_empty']}, "
                f"multisig_txs_changed={counters['multisig_txs_changed']}, "
                f"module_txs_changed={counters['module_txs_changed']}"
            )
        )

    # ------------------------------------------------------------------
    # Step 2: traces that do not match the Safe events
    # ------------------------------------------------------------------
    @staticmethod
    def _trace_key(internal_tx: InternalTx) -> tuple:
        """
        :param internal_tx: Stored or built from a trace
        :return: Hashable key with the ``TRACE_KEY_FIELDS`` values
        """
        return tuple(
            bytes(value)
            if field == "data" and (value := getattr(internal_tx, field)) is not None
            else getattr(internal_tx, field)
            for field in TRACE_KEY_FIELDS
        )

    def _sync_traces(
        self, traces_per_tx: dict[bytes, list[FilterTrace]]
    ) -> tuple[int, int]:
        """
        Make the stored traces of the txs match ``trace_transaction``: delete the
        stored traces that are not on chain and index the relevant traces that are
        missing. A trace stored under a wrong ``trace_address`` takes the place of
        the real trace, which would be ignored when the tx is indexed again. It runs
        in one transaction, so a tx is never left with its traces deleted and the
        real ones not indexed.

        :param traces_per_tx: Traces on chain per tx hash. Txs not stored are indexed
        :return: Number of stored traces deleted and number of txs indexed
        """
        tracing = self.tracing_indexer.ethereum_client.tracing
        tx_hashes = [to_0x_hex_str(tx_hash) for tx_hash in traces_per_tx]
        rows_per_tx: dict[str, list[InternalTx]] = defaultdict(list)
        for row in InternalTx.objects.filter(ethereum_tx__in=tx_hashes).only(
            "ethereum_tx", *TRACE_KEY_FIELDS
        ):
            rows_per_tx[row.ethereum_tx_id].append(row)
        ethereum_txs = {
            ethereum_tx.tx_hash: ethereum_tx
            for ethereum_tx in EthereumTx.objects.filter(tx_hash__in=tx_hashes)
            .select_related("block")
            .only("tx_hash", "block_id", "block__timestamp")
        }

        wrong_ids: list[int] = []
        to_index: dict[bytes, list[FilterTrace]] = {}
        for tx_hash, traces in traces_per_tx.items():
            # The traces indexer only indexes txs that call a Safe singleton. Other
            # txs are stored for other reasons (e.g. ERC20 transfers) and their
            # traces must not be indexed
            if not self.tracing_indexer._extract_safe_proxies(
                traces, self.master_copies
            ):
                continue
            ethereum_tx = ethereum_txs.get(to_0x_hex_str(tx_hash))
            if not ethereum_tx:
                to_index[tx_hash] = traces
                continue
            # Errored traces are never stored
            keys_on_chain = {
                self._trace_key(
                    InternalTx.objects.build_from_trace(trace, ethereum_tx)
                ): trace
                for trace in cast(
                    list[FilterTrace], tracing.filter_out_errored_traces(traces)
                )
            }
            stored = {
                row.pk: self._trace_key(row) for row in rows_per_tx[ethereum_tx.tx_hash]
            }
            stored_keys = set(stored.values())
            tx_wrong_ids = [
                pk for pk, key in stored.items() if key not in keys_on_chain
            ]
            is_missing_traces = any(
                key not in stored_keys and InternalTxIndexer.is_relevant_trace(trace)
                for key, trace in keys_on_chain.items()
            )
            if tx_wrong_ids or is_missing_traces:
                self.stdout.write(
                    f"Tx {ethereum_tx.tx_hash}: deleting {len(tx_wrong_ids)} traces "
                    f"not on chain, missing traces={is_missing_traces}"
                )
                wrong_ids.extend(tx_wrong_ids)
                to_index[tx_hash] = traces

        # Deleting a decoded trace deletes the status and the module tx built from it
        changed_safes = list(
            InternalTxDecoded.objects.filter(internal_tx_id__in=wrong_ids)
            .values_list("safe_address", flat=True)
            .distinct()
        )
        self._add_safes_to_fix(changed_safes)
        if to_index and not self.dry_run:
            with transaction.atomic():
                InternalTx.objects.filter(pk__in=wrong_ids).delete()
                # `process_elements` receives the list of traces of every tx, as
                # returned by `trace_transactions`
                self.tracing_indexer.process_elements(to_index)  # type: ignore[arg-type]
            self._remove_cached_views(changed_safes)
        return len(wrong_ids), len(to_index)

    def _mismatched_txs(
        self, from_block: int, to_block: int
    ) -> tuple[int, list[bytes]]:
        """
        Count the Safe events of every tx of the blocks per Safe and kind, and compare
        them with the decoded traces of the tx. Safes older than v1.3.0 do not emit
        every event, so their txs can also not match. Syncing them changes nothing.

        :param from_block:
        :param to_block:
        :return: Number of txs with Safe events and the hashes of the txs that do not
            match
        """
        on_chain = Counter[tuple[bytes, ChecksumAddress, str]]()
        for log in self.ethereum_client.slow_w3.eth.get_logs(
            {
                "fromBlock": from_block,
                "toBlock": to_block,
                "topics": [[to_0x_hex_str(topic) for topic in self.event_kinds]],
            }
        ):
            on_chain[
                (
                    bytes(HexBytes(log["transactionHash"])),
                    fast_to_checksum_address(log["address"]),
                    self.event_kinds[bytes(HexBytes(log["topics"][0]))],
                )
            ] += 1
        tx_hashes = list(dict.fromkeys(tx_hash for tx_hash, _, _ in on_chain))
        stored = Counter(
            (bytes(HexBytes(tx_hash)), safe_address, FUNCTION_EVENTS[function_name])
            for tx_hash, safe_address, function_name in InternalTxDecoded.objects.filter(
                internal_tx__ethereum_tx__in=[
                    to_0x_hex_str(tx_hash) for tx_hash in tx_hashes
                ],
                function_name__in=FUNCTION_EVENTS,
            ).values_list("internal_tx__ethereum_tx", "safe_address", "function_name")
        )
        mismatched = {
            tx_hash for tx_hash, _, _ in (on_chain - stored) + (stored - on_chain)
        }
        return len(tx_hashes), [
            tx_hash for tx_hash in tx_hashes if tx_hash in mismatched
        ]

    def sync_mismatched_traces(self) -> None:
        """
        Sync with ``trace_transaction`` the traces of the txs of the range whose Safe
        events do not match their decoded traces, a window of blocks at a time. It
        finds the txs whose traces were skipped by ``trace_filter`` of the bad node,
        also when the whole tx is not stored, and the txs with traces stored under a
        wrong ``traceAddress``.
        """
        self.stdout.write(
            self.style.MIGRATE_HEADING("Syncing the traces that do not match the logs")
        )
        counters = Counter[str]()
        windows = range(self.from_block, self.to_block + 1, LOGS_BLOCK_WINDOW)
        for checked, window_from in enumerate(windows, start=1):
            window_to = min(window_from + LOGS_BLOCK_WINDOW - 1, self.to_block)
            txs_with_events, tx_hashes = self._mismatched_txs(window_from, window_to)
            counters["txs"] += txs_with_events
            counters["mismatched_txs"] += len(tx_hashes)
            if tx_hashes:
                # One call for the window, so the batches are requested in parallel
                traces = self.tracing_indexer.trace_transactions(
                    [to_0x_hex_str(tx_hash) for tx_hash in tx_hashes],
                    batch_size=RPC_BATCH_SIZE,
                )
                for traces_chunk in chunks(
                    list(zip(tx_hashes, traces, strict=True)), RPC_BATCH_SIZE
                ):
                    deleted, changed = self._sync_traces(dict(traces_chunk))
                    counters["deleted"] += deleted
                    counters["changed_txs"] += changed
            self._progress(checked, len(windows), "Block windows checked")

        action = "Would change" if self.dry_run else "Changed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} the traces of {counters['changed_txs']} txs. "
                f"txs_with_safe_events={counters['txs']}, "
                f"mismatched_txs={counters['mismatched_txs']}, "
                f"traces_deleted={counters['deleted']}, "
                f"safes_to_fix={len(self.safes_to_fix)}"
            )
        )

    # ------------------------------------------------------------------
    # Step 3: fix the Safes
    # ------------------------------------------------------------------
    def check_safe(self, address: ChecksumAddress) -> SafeRepair:
        """
        Find the wrong multisig txs of the Safe and the point to process it again
        from.

        An executed multisig tx is wrong if its tx has execution events of the Safe
        and none of them has its ``safe_tx_hash``. The Safe is processed again from
        the first wrong multisig tx or the first multisig tx of a repeated executed
        nonce. Every execution after that point is processed again, so its multisig
        txs that cannot be checked (their tx has no execution events of the Safe)
        are removed too, as processing builds them again. Right multisig txs are
        not changed, so no events are sent for them.

        :param address:
        :return: Action and rows to change
        """
        if address in self.banned_safes:
            return SafeRepair(address, SafeAction.SKIP_BANNED)

        repair = SafeRepair(address, SafeAction.OK)
        previous_nonce: int | None = None
        previous_block: tuple[datetime, int] | None = None
        # Multisig txs that cannot be checked: hash, block time, created by the indexer
        unchecked: list[tuple[HexStr, datetime, bool]] = []
        # Inside a transaction the cursor is not materialized in the database, the
        # rows are streamed with the logs of their tx
        with transaction.atomic():
            for (
                safe_tx_hash,
                nonce,
                created,
                origin,
                proposer,
                logs,
                block_number,
                block_timestamp,
            ) in (
                MultisigTransaction.objects.executed()
                .filter(safe=address)
                # Order of the `(safe, -nonce, -created)` index, the rows of a nonce
                # come together
                .order_by("-nonce", "-created")
                .values_list(
                    "safe_tx_hash",
                    "nonce",
                    "created",
                    "origin",
                    "proposer",
                    "ethereum_tx__logs",
                    "ethereum_tx__block_id",
                    "ethereum_tx__block__timestamp",
                )
                .iterator(chunk_size=ITERATOR_CHUNK_SIZE)
            ):
                # Created by the indexer: `created` is the block time and it has no
                # origin and no proposer. Rows proposed using the API can also have no
                # origin and no proposer, but `created` is the time they were
                # received. Rows proposed by users are unlinked, as their data cannot
                # be rebuilt
                created_by_indexer = (
                    created == block_timestamp and origin == {} and proposer is None
                )
                block = (block_timestamp, block_number)
                is_right = self._is_right_execution(logs, address, safe_tx_hash)
                if is_right is False:
                    self._add_to_repair(repair, safe_tx_hash, created_by_indexer)
                    self._set_reset_point(repair, block)
                elif is_right is None:
                    unchecked.append(
                        (safe_tx_hash, block_timestamp, created_by_indexer)
                    )
                if nonce == previous_nonce:
                    # Repeated nonce, every row of it can be the first one
                    self._set_reset_point(repair, cast(tuple, previous_block))
                    self._set_reset_point(repair, block)
                previous_nonce, previous_block = nonce, block

        if repair.from_timestamp is not None:
            repair.action = SafeAction.RESET
            for safe_tx_hash, block_timestamp, created_by_indexer in unchecked:
                if block_timestamp >= repair.from_timestamp:
                    self._add_to_repair(repair, safe_tx_hash, created_by_indexer)
        return repair

    @staticmethod
    def _set_reset_point(repair: SafeRepair, block: tuple[datetime, int]) -> None:
        """
        Move the point to process the Safe again from to the block, if it is earlier

        :param repair:
        :param block: Block time and number
        """
        if repair.from_timestamp is None or block[0] < repair.from_timestamp:
            repair.from_timestamp, repair.from_block = block

    @staticmethod
    def _add_to_repair(
        repair: SafeRepair, safe_tx_hash: HexStr, created_by_indexer: bool
    ) -> None:
        """
        Add a multisig tx to delete if it was created by the indexer, or to unlink if
        it was proposed by a user

        :param repair:
        :param safe_tx_hash:
        :param created_by_indexer:
        """
        if created_by_indexer:
            repair.to_delete.append(safe_tx_hash)
        else:
            repair.to_unlink.append(safe_tx_hash)

    @staticmethod
    def _in_batches(elements: list[Any], lock: Lock) -> Iterator[list[Any]]:
        """
        :param elements: Keys of the rows to change
        :param lock: Safe processing lock, renewed before every batch. It fails if the
            lock expired, so nothing is changed without holding it
        :return: The elements in batches of ``DB_BATCH_SIZE``
        """
        for batch in chunks(elements, DB_BATCH_SIZE):
            lock.reacquire()
            yield batch

    def _apply(self, repair: SafeRepair, lock: Lock) -> None:
        """
        Mark the decoded txs of the Safe as not processed and delete its statuses
        from the reset point, then delete and unlink the wrong multisig txs. The
        workers then process the Safe again from the last status before that point.
        It is the reset of ``IndexService.fix_out_of_order`` done in batches renewing
        the lock, as big Safes have millions of rows.

        The last status is deleted at the end: if the command stops in the middle,
        the workers find decoded txs out of order and ``fix_out_of_order`` resets the
        Safe and its multisig txs.

        :param repair:
        :param lock: Safe processing lock, renewed before every batch
        """
        address = repair.address
        # Filtering by `_from` uses its `InternalTx` index, `safe_address` only has
        # partial indexes that do not cover processed rows
        decoded = InternalTxDecoded.objects.filter(
            internal_tx___from=address,
            safe_address=address,
            processed=True,
            internal_tx__timestamp__gte=repair.from_timestamp,
        )
        # A status is built from a processed decoded tx, and both use its trace as
        # primary key. The rows are read once, with one index scan
        for pks in self._in_batches(list(decoded.values_list("pk", flat=True)), lock):
            # Together, as a decoded tx not processed is not selected again
            with transaction.atomic():
                InternalTxDecoded.objects.filter(pk__in=pks).update(processed=False)
                SafeStatus.objects.filter(pk__in=pks).delete()
        index_service = IndexServiceProvider()
        for safe_tx_hashes in self._in_batches(repair.to_delete, lock):
            index_service.delete_executed_multisig_txs(safe_tx_hashes)
        for safe_tx_hashes in self._in_batches(repair.to_unlink, lock):
            index_service.unlink_executed_multisig_txs(safe_tx_hashes)
        SafeLastStatus.objects.filter(address=address).delete()
        # The deletes and updates above send no signals
        self._remove_cached_views([address])

    def fix_safe(self, address: ChecksumAddress) -> SafeRepair:
        """
        Check again and fix the Safe holding the lock of the task that processes it,
        so the workers do not change it between the check and the fix. The lock waits
        for a running task of the Safe to end.

        :param address:
        :return: Repair applied
        :raises LockError: If the lock cannot be taken or is lost
        """
        lock_name = get_task_lock_name(
            process_decoded_internal_txs_for_safe_task.name, lock_name_suffix=address
        )
        with get_redis().lock(
            lock_name, timeout=SAFE_LOCK_TIMEOUT, blocking_timeout=LOCK_TIMEOUT
        ) as lock:
            repair = self.check_safe(address)
            if repair.action == SafeAction.RESET:
                self._apply(repair, lock)
        return repair

    def fix_safes(self, addresses: list[ChecksumAddress] | None) -> None:
        """
        Check the affected Safes against the logs and fix the wrong ones.

        :param addresses: Safes to fix, or ``None`` for the Safes found as in
            ``--addresses``. A Safe is only locked when it must be reset
        """
        self.stdout.write(self.style.MIGRATE_HEADING("Fixing the Safes"))
        if addresses:
            # Without repeated Safes, in the given order
            safes = list(dict.fromkeys(addresses))
        else:
            safes = sorted(
                self.safes_with_repeated_executed_nonces
                | self.safes_with_wrong_executions_in_range
                | self.safes_to_fix
            )
        self.stdout.write(f"Checking {len(safes)} Safes")
        actions = Counter[SafeAction]()
        totals = Counter[str]()
        failed: list[ChecksumAddress] = []
        checked = 0
        for address in safes:
            if (
                self.max_safes is not None
                and actions[SafeAction.RESET] >= self.max_safes
            ):
                break
            checked += 1
            self._progress(checked, len(safes), "Safes checked")
            repair = self.check_safe(address)
            if repair.action == SafeAction.RESET and not self.dry_run:
                try:
                    repair = self.fix_safe(address)
                except LockError as exc:
                    failed.append(address)
                    self.stdout.write(
                        self.style.ERROR(f"[{address}] Cannot hold its lock: {exc}")
                    )
                    continue
            actions[repair.action] += 1
            totals["deleted"] += len(repair.to_delete)
            totals["unlinked"] += len(repair.to_unlink)
            self.stdout.write(
                f"[{address}] action={repair.action} from_block={repair.from_block} "
                f"to_delete={len(repair.to_delete)} to_unlink={len(repair.to_unlink)}"
            )

        if checked < len(safes):
            self.stdout.write(
                self.style.WARNING(
                    f"Reached --max-safes={self.max_safes}, run again with "
                    f"--only-fix-safes for the remaining {len(safes) - checked} Safes, "
                    f"adding with --addresses the ones printed as 'Safe to fix'"
                )
            )
        for address in failed:
            self.stdout.write(self.style.ERROR(f"Safe not fixed, run again: {address}"))
        action = "Would fix" if self.dry_run else "Fixed"
        actions_text = ", ".join(
            f"{name}={count}" for name, count in sorted(actions.items())
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {actions[SafeAction.RESET]} Safes. {actions_text}, "
                f"multisig_txs_deleted={totals['deleted']}, "
                f"multisig_txs_unlinked={totals['unlinked']}, failed={len(failed)}"
            )
        )
