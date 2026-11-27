# SPDX-License-Identifier: FSL-1.1-MIT
from collections import OrderedDict
from datetime import timedelta
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

import factory
from eth_account import Account
from eth_utils import event_abi_to_log_topic
from hexbytes import HexBytes
from redis.exceptions import LockError
from safe_eth.eth.contracts import get_safe_V1_3_0_contract
from safe_eth.eth.ethereum_client import EthereumClient
from web3 import Web3

from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.tasks import LOCK_TIMEOUT, get_task_lock_name

from ..indexers import InternalTxIndexer
from ..management.commands.fix_gnosis_chain_indexing_mismatch import (
    DEFAULT_FROM_BLOCK,
    DEFAULT_TO_BLOCK,
    SAFE_LOCK_TIMEOUT,
    Command,
)
from ..models import (
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    InternalTxType,
    MultisigConfirmation,
    MultisigTransaction,
    SafeLastStatus,
    SafeStatus,
)
from ..services import IndexServiceProvider
from ..tasks import process_decoded_internal_txs_for_safe_task
from .factories import (
    EthereumBlockFactory,
    EthereumTxFactory,
    InternalTxDecodedFactory,
    InternalTxFactory,
    ModuleTransactionFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
    SafeStatusFactory,
)

COMMAND = "fix_gnosis_chain_indexing_mismatch"
MODULE = f"safe_transaction_service.history.management.commands.{COMMAND}"
TRACING_NODE_URL = "http://localhost:8545"
_SAFE_EVENTS = get_safe_V1_3_0_contract(Web3()).events
EXECUTION_SUCCESS_TOPIC = HexBytes(
    event_abi_to_log_topic(_SAFE_EVENTS.ExecutionSuccess().abi)
)
MODULE_SUCCESS_TOPIC = HexBytes(
    event_abi_to_log_topic(_SAFE_EVENTS.ExecutionFromModuleSuccess().abi)
)
MODULE_FAILURE_TOPIC = HexBytes(
    event_abi_to_log_topic(_SAFE_EVENTS.ExecutionFromModuleFailure().abi)
)
SAFE_SETUP_TOPIC = HexBytes(event_abi_to_log_topic(_SAFE_EVENTS.SafeSetup().abi))
EXEC_TRANSACTION_DATA = b"\x6a\x76\x12\x02"

_BASE_TIME = timezone.now() - timedelta(days=30)


class OrderedEthereumBlockFactory(EthereumBlockFactory):
    """
    Block whose timestamp grows with its number, as a Safe is reset from a block
    timestamp. A block with the same number is reused
    """

    class Meta:
        django_get_or_create = ("number",)

    timestamp = factory.LazyAttribute(
        lambda block: _BASE_TIME + timedelta(seconds=5 * block.number)
    )


class EtherRefundInternalTxFactory(InternalTxFactory):
    """
    Ether refund a Safe pays to the executor at the end of ``execTransaction``
    """

    data = None
    value = 1000
    gas = 2300
    gas_used = 0


class ExecTransactionInternalTxFactory(InternalTxFactory):
    """
    Delegate call of a Safe to its singleton for ``execTransaction``
    """

    trace_address = "0"
    call_type = EthereumTxCallType.DELEGATE_CALL.value
    tx_type = InternalTxType.CALL.value
    value = 0
    gas = 100_000
    gas_used = 50_000
    data = HexBytes(EXEC_TRANSACTION_DATA)


def _trace(
    trace_address: list[int],
    _from: str,
    to: str,
    call_type: str = "call",
    value: int = 0,
    gas: int = 2300,
    gas_used: int = 0,
    data: bytes = b"",
) -> dict:
    return {
        "action": {
            "from": _from,
            "to": to,
            "callType": call_type,
            "gas": gas,
            "value": value,
            "input": HexBytes(data),
        },
        "result": {"gasUsed": gas_used, "output": HexBytes("0x")},
        "traceAddress": trace_address,
        "subtraces": 0,
        "type": "call",
        "transactionHash": HexBytes(b"\x01" * 32),
        "blockHash": HexBytes(b"\x02" * 32),
        "blockNumber": 100,
        "transactionPosition": 0,
    }


def _exec_transaction_trace(safe: str, singleton: str, trace_address=(0,)) -> dict:
    return _trace(
        list(trace_address),
        safe,
        singleton,
        call_type="delegatecall",
        gas=100_000,
        gas_used=50_000,
        data=EXEC_TRANSACTION_DATA,
    )


def _execution_success_log(safe: str, safe_tx_hash: str) -> dict:
    """
    :return: v1.3.0 ``ExecutionSuccess`` log as stored in ``EthereumTx.logs``
    """
    return {
        "address": safe,
        "topics": [EXECUTION_SUCCESS_TOPIC.to_0x_hex()],
        "data": HexBytes(HexBytes(safe_tx_hash) + bytes(32)).to_0x_hex(),
    }


def _raw_log(safe: str, topic: HexBytes, tx_hash: HexBytes | None = None) -> dict:
    """
    :return: Safe event log as returned by the node
    """
    log = {"address": safe, "topics": [topic], "data": HexBytes(b"\x01" * 64)}
    if tx_hash is not None:
        log["transactionHash"] = tx_hash
    return log


def _raw_execution_log(safe: str, tx_hash: HexBytes | None = None) -> dict:
    """
    :return: ``ExecutionSuccess`` log as returned by the node
    """
    return _raw_log(safe, EXECUTION_SUCCESS_TOPIC, tx_hash)


def _safe_lock_name(address: str) -> str:
    return get_task_lock_name(
        process_decoded_internal_txs_for_safe_task.name, lock_name_suffix=address
    )


@override_settings(ETHEREUM_TRACING_NODE_URL=TRACING_NODE_URL)
class TestFixGnosisChainIndexingMismatchCommand(TestCase):
    @staticmethod
    def _command(**options) -> tuple[Command, StringIO]:
        """
        :param options: ``Command.setup`` options. The range is blocks 100-200
        :return: Command ready to run its steps and its output
        """
        output = StringIO()
        command = Command(stdout=output)
        command.setup(**{"from_block": 100, "to_block": 200, **options})
        return command, output

    @staticmethod
    def _executed_multisig_tx(
        safe_address: str,
        nonce: int,
        logged: bool = True,
        block_number: int = 1_000,
        logs: list[dict] | None = None,
        **kwargs,
    ) -> MultisigTransaction:
        """
        :param logged: Store the execution log of the multisig tx in its tx
        :param logs: Logs of its tx, instead of an execution log
        :return: Executed multisig tx created by the indexer
        """
        ethereum_tx = EthereumTxFactory(
            block=OrderedEthereumBlockFactory(number=block_number)
        )
        multisig_tx = MultisigTransactionFactory(
            **{
                "safe": safe_address,
                "nonce": nonce,
                "ethereum_tx": ethereum_tx,
                "created": ethereum_tx.block.timestamp,
                "origin": {},
                "proposer": None,
                **kwargs,
            }
        )
        execution_hash = (
            multisig_tx.safe_tx_hash if logged else HexBytes(b"\xee" * 32).to_0x_hex()
        )
        ethereum_tx.logs = (
            [_execution_success_log(safe_address, execution_hash)]
            if logs is None
            else logs
        )
        ethereum_tx.save(update_fields=["logs"])
        return multisig_tx

    def test_arguments(self):
        with self.assertRaisesMessage(CommandError, "lower or equal"):
            call_command(
                COMMAND, "--from-block=200", "--to-block=100", stdout=StringIO()
            )
        with self.assertRaisesMessage(CommandError, "Invalid Ethereum address"):
            call_command(COMMAND, "--addresses", "0x1234", stdout=StringIO())

        output = StringIO()
        call_command(COMMAND, "--only-fix-safes", "--dry-run", stdout=output)
        self.assertIn(
            f"Range: blocks {DEFAULT_FROM_BLOCK}-{DEFAULT_TO_BLOCK}", output.getvalue()
        )
        self.assertIn("Would fix 0 Safes", output.getvalue())

    # ------------------------------------------------------------------
    # Empty logs
    # ------------------------------------------------------------------
    @mock.patch.object(EthereumClient, "get_transaction_receipts", autospec=True)
    def test_fix_empty_logs(self, get_transaction_receipts_mock: MagicMock):
        block_in_range = EthereumBlockFactory(number=150)
        block_out_of_range = EthereumBlockFactory(number=500)
        empty_tx = EthereumTxFactory(block=block_in_range, logs=[], status=1)
        legit_empty_tx = EthereumTxFactory(block=block_in_range, logs=None, status=1)
        out_of_range_tx = EthereumTxFactory(block=block_out_of_range, logs=[])
        with_logs_tx = EthereumTxFactory(
            block=block_in_range,
            logs=[{"address": Account.create().address, "data": "0x", "topics": []}],
        )
        safe_address = Account.create().address
        module_address = Account.create().address
        # Processed from the receipt without logs
        multisig_tx = MultisigTransactionFactory(
            safe=safe_address, ethereum_tx=empty_tx, failed=None, payment=None
        )
        module_tx = ModuleTransactionFactory(
            safe=safe_address,
            module=module_address,
            internal_tx__ethereum_tx=empty_tx,
            failed=False,
        )
        # Processed with a wrong nonce: its hash is not in the logs
        safe_wrong_hash = Account.create().address
        MultisigTransactionFactory(safe=safe_wrong_hash, ethereum_tx=empty_tx)
        receipts_by_hash = {
            HexBytes(empty_tx.tx_hash): {
                "status": 1,
                "logs": [
                    {
                        "address": safe_address,
                        "data": HexBytes(multisig_tx.safe_tx_hash)
                        + (7).to_bytes(32, "big"),
                        "topics": [EXECUTION_SUCCESS_TOPIC],
                    },
                    {
                        "address": safe_address,
                        "data": HexBytes(b""),
                        "topics": [
                            MODULE_FAILURE_TOPIC,
                            HexBytes(module_address).rjust(32, b"\x00"),
                        ],
                    },
                    _raw_execution_log(safe_wrong_hash),
                ],
            },
            HexBytes(legit_empty_tx.tx_hash): {"status": 1, "logs": []},
        }
        get_transaction_receipts_mock.side_effect = lambda _, tx_hashes: [
            receipts_by_hash[HexBytes(tx_hash)] for tx_hash in tx_hashes
        ]

        command, output = self._command(dry_run=True)
        command.fix_empty_logs()
        self.assertIn("Found 2 txs without logs", output.getvalue())
        self.assertIn(
            "Would update logs of 1/2 txs. still_empty=1, "
            "multisig_txs_changed=1, module_txs_changed=1",
            output.getvalue(),
        )
        empty_tx.refresh_from_db()
        self.assertEqual(empty_tx.logs, [])

        command, output = self._command()
        command.fix_empty_logs()
        self.assertIn("Updated logs of 1/2 txs", output.getvalue())
        empty_tx.refresh_from_db()
        self.assertEqual(len(empty_tx.logs), 3)
        self.assertEqual(empty_tx.logs[0]["address"], safe_address)
        multisig_tx.refresh_from_db()
        self.assertFalse(multisig_tx.failed)
        self.assertEqual(multisig_tx.payment, 7)
        module_tx.refresh_from_db()
        self.assertTrue(module_tx.failed)
        # With the new logs, the Safe processed with a wrong nonce is found when
        # fixing the Safes
        self.assertEqual(
            command.safes_with_wrong_executions_in_range, {safe_wrong_hash}
        )
        # Not in range or already with logs, never fetched
        fetched = {
            HexBytes(tx_hash)
            for call in get_transaction_receipts_mock.call_args_list
            for tx_hash in call.args[1]
        }
        self.assertFalse(
            fetched
            & {HexBytes(out_of_range_tx.tx_hash), HexBytes(with_logs_tx.tx_hash)}
        )

    # ------------------------------------------------------------------
    # Traces that do not match the Safe events
    # ------------------------------------------------------------------
    @mock.patch(f"{MODULE}.get_auto_ethereum_client")
    def test_mismatched_txs(self, get_auto_ethereum_client_mock: MagicMock):
        get_logs_mock = get_auto_ethereum_client_mock.return_value.slow_w3.eth.get_logs
        safe_address = Account.create().address
        # Execution indexed
        matching_tx = EthereumTxFactory()
        InternalTxDecodedFactory(
            internal_tx__ethereum_tx=matching_tx,
            internal_tx___from=safe_address,
            function_name="execTransaction",
        )
        # Module execution not indexed
        module_tx = HexBytes(b"\x0b" * 32)
        # `setup` indexed twice, once from a trace with a wrong trace address
        setup_tx = EthereumTxFactory()
        for _ in range(2):
            InternalTxDecodedFactory(
                internal_tx__ethereum_tx=setup_tx,
                internal_tx___from=safe_address,
                function_name="setup",
            )
        get_logs_mock.return_value = [
            _raw_execution_log(safe_address, HexBytes(matching_tx.tx_hash)),
            _raw_log(safe_address, MODULE_SUCCESS_TOPIC, module_tx),
            _raw_log(safe_address, SAFE_SETUP_TOPIC, HexBytes(setup_tx.tx_hash)),
        ]

        command, _ = self._command()
        self.assertEqual(
            command._mismatched_txs(100, 200),
            (3, [module_tx, HexBytes(setup_tx.tx_hash)]),
        )
        params = get_logs_mock.call_args.args[0]
        self.assertEqual(params["fromBlock"], 100)
        self.assertEqual(params["toBlock"], 200)
        self.assertEqual(
            {HexBytes(topic) for topic in params["topics"][0]},
            {
                EXECUTION_SUCCESS_TOPIC,
                MODULE_SUCCESS_TOPIC,
                MODULE_FAILURE_TOPIC,
                SAFE_SETUP_TOPIC,
            }
            | {
                HexBytes(topic)
                for topic in command.tx_processor.safe_tx_execution_events_topics
            },
        )

    @mock.patch.object(InternalTxIndexer, "process_elements", autospec=True)
    @mock.patch.object(InternalTxIndexer, "trace_transactions", autospec=True)
    @mock.patch(f"{MODULE}.get_auto_ethereum_client")
    def test_sync_mismatched_traces(
        self,
        get_auto_ethereum_client_mock: MagicMock,
        trace_transactions_mock: MagicMock,
        process_elements_mock: MagicMock,
    ):
        get_logs_mock = get_auto_ethereum_client_mock.return_value.slow_w3.eth.get_logs
        master_copy = SafeMasterCopyFactory().address
        block = OrderedEthereumBlockFactory(number=150)
        safe_address = Account.create().address
        receiver = Account.create().address
        safe_tx = EthereumTxFactory(block=block)
        refund = {"ethereum_tx": safe_tx, "_from": safe_address, "to": receiver}
        # The execution was not decoded
        execution = ExecTransactionInternalTxFactory(
            ethereum_tx=safe_tx, _from=safe_address, to=master_copy
        )
        # Same refund transfer stored twice. On chain `0,1` is the refund and
        # `0,0` is a different call, so the row at `0,0` is wrong
        wrong_trace = EtherRefundInternalTxFactory(trace_address="0,0", **refund)
        InternalTxDecodedFactory(
            internal_tx=wrong_trace, function_name="transfer", processed=True
        )
        right_trace = EtherRefundInternalTxFactory(trace_address="0,1", **refund)
        # Gas is not compared: nodes of different clients can report another gas
        other_gas_trace = EtherRefundInternalTxFactory(
            trace_address="0,2", gas=5000, **refund
        )
        # Repeated call that exists twice on chain too
        legit_1 = EtherRefundInternalTxFactory(trace_address="0,3", value=7, **refund)
        legit_2 = EtherRefundInternalTxFactory(trace_address="0,4", value=7, **refund)
        # Stored for an ERC20 transfer, it has no Safe events
        EthereumTxFactory(block=block)
        get_logs_mock.return_value = [
            _raw_execution_log(safe_address, HexBytes(safe_tx.tx_hash))
        ]
        safe_traces = [
            _trace([], Account.create().address, safe_address, gas=100_000),
            _exec_transaction_trace(safe_address, master_copy),
            _trace([0, 0], safe_address, receiver, gas=9000, data=b"\xab\xcd"),
            _trace([0, 1], safe_address, receiver, value=1000),
            _trace([0, 2], safe_address, receiver, value=1000, gas=6000),
            _trace([0, 3], safe_address, receiver, value=7),
            _trace([0, 4], safe_address, receiver, value=7),
        ]
        trace_transactions_mock.return_value = [safe_traces]

        command, output = self._command(dry_run=True)
        command.sync_mismatched_traces()
        self.assertIn(
            "Would change the traces of 1 txs. txs_with_safe_events=1, "
            "mismatched_txs=1, traces_deleted=1, safes_to_fix=1",
            output.getvalue(),
        )
        # The deleted trace was decoded, its Safe must be fixed
        self.assertIn(f"Safe to fix: {safe_address}", output.getvalue())
        process_elements_mock.assert_not_called()
        self.assertTrue(InternalTx.objects.filter(pk=wrong_trace.pk).exists())

        command, output = self._command()
        command.sync_mismatched_traces()
        self.assertIn("Changed the traces of 1 txs", output.getvalue())
        # The traces on chain are indexed in case one was skipped
        self.assertEqual(
            process_elements_mock.call_args.args[1],
            OrderedDict([(HexBytes(safe_tx.tx_hash), safe_traces)]),
        )
        self.assertFalse(InternalTx.objects.filter(pk=wrong_trace.pk).exists())
        self.assertFalse(
            InternalTxDecoded.objects.filter(internal_tx_id=wrong_trace.pk).exists()
        )
        for internal_tx in (execution, right_trace, other_gas_trace, legit_1, legit_2):
            self.assertTrue(InternalTx.objects.filter(pk=internal_tx.pk).exists())

        # Nothing missing on chain: the tx is not changed
        process_elements_mock.reset_mock()
        trace_transactions_mock.return_value = [[safe_traces[1], *safe_traces[3:]]]
        command, output = self._command()
        command.sync_mismatched_traces()
        self.assertIn(
            "Changed the traces of 0 txs. txs_with_safe_events=1, mismatched_txs=1",
            output.getvalue(),
        )
        process_elements_mock.assert_not_called()

        # Every Safe event has its decoded trace: the tx is not traced
        trace_transactions_mock.reset_mock()
        InternalTxDecodedFactory(internal_tx=execution, function_name="execTransaction")
        command, output = self._command()
        command.sync_mismatched_traces()
        self.assertIn("mismatched_txs=0", output.getvalue())
        trace_transactions_mock.assert_not_called()

    @mock.patch.object(InternalTxIndexer, "process_elements", autospec=True)
    @mock.patch.object(InternalTxIndexer, "trace_transactions", autospec=True)
    @mock.patch(f"{MODULE}.get_auto_ethereum_client")
    def test_sync_mismatched_traces_not_stored_executions(
        self,
        get_auto_ethereum_client_mock: MagicMock,
        trace_transactions_mock: MagicMock,
        process_elements_mock: MagicMock,
    ):
        get_logs_mock = get_auto_ethereum_client_mock.return_value.slow_w3.eth.get_logs
        master_copy = SafeMasterCopyFactory().address
        safe_missing = Account.create().address
        safe_not_monitored = Account.create().address
        tx_missing = HexBytes(b"\x0a" * 32)
        tx_not_monitored = HexBytes(b"\x0c" * 32)
        # `trace_filter` of the bad node skipped these txs, they are not stored
        get_logs_mock.return_value = [
            _raw_execution_log(safe_missing, tx_missing),
            _raw_execution_log(safe_not_monitored, tx_not_monitored),
        ]
        traces = {
            tx_missing: [_exec_transaction_trace(safe_missing, master_copy)],
            tx_not_monitored: [
                _exec_transaction_trace(safe_not_monitored, Account.create().address)
            ],
        }
        trace_transactions_mock.side_effect = lambda _, tx_hashes, batch_size: [
            traces[HexBytes(tx_hash)] for tx_hash in tx_hashes
        ]

        command, output = self._command(dry_run=True)
        command.sync_mismatched_traces()
        self.assertIn("Would change the traces of 1 txs", output.getvalue())
        process_elements_mock.assert_not_called()

        command, output = self._command()
        command.sync_mismatched_traces()
        self.assertIn(
            "Changed the traces of 1 txs. txs_with_safe_events=2, mismatched_txs=2",
            output.getvalue(),
        )
        # The tx calling a singleton that is not monitored is not indexed
        self.assertEqual(
            process_elements_mock.call_args.args[1],
            OrderedDict([(tx_missing, traces[tx_missing])]),
        )

    @mock.patch.object(InternalTxIndexer, "process_elements", autospec=True)
    @mock.patch.object(InternalTxIndexer, "trace_transactions", autospec=True)
    @mock.patch(f"{MODULE}.get_auto_ethereum_client")
    def test_sync_mismatched_traces_missing_execution_in_stored_tx(
        self,
        get_auto_ethereum_client_mock: MagicMock,
        trace_transactions_mock: MagicMock,
        process_elements_mock: MagicMock,
    ):
        get_logs_mock = get_auto_ethereum_client_mock.return_value.slow_w3.eth.get_logs
        master_copy = SafeMasterCopyFactory().address
        safe_address = Account.create().address
        executor = Account.create().address
        ethereum_tx = EthereumTxFactory(block=OrderedEthereumBlockFactory(number=150))
        tx_hash = HexBytes(ethereum_tx.tx_hash)
        # The tx executes 2 txs of the Safe, only the first one was indexed
        indexed_execution = ExecTransactionInternalTxFactory(
            ethereum_tx=ethereum_tx, _from=safe_address, to=master_copy
        )
        InternalTxDecodedFactory(
            internal_tx=indexed_execution, function_name="execTransaction"
        )
        # The refund is stored at the trace address of the second execution
        wrong_trace = EtherRefundInternalTxFactory(
            ethereum_tx=ethereum_tx, _from=safe_address, to=executor, trace_address="1"
        )
        execution_log = _raw_execution_log(safe_address, tx_hash)
        get_logs_mock.return_value = [execution_log, execution_log]
        traces = [
            _exec_transaction_trace(safe_address, master_copy),
            _exec_transaction_trace(safe_address, master_copy, trace_address=(1,)),
            _trace([1, 0], safe_address, executor, value=1000),
        ]
        trace_transactions_mock.return_value = [traces]

        command, output = self._command()
        command.sync_mismatched_traces()
        trace_transactions_mock.assert_called_once()
        self.assertIn(
            "Changed the traces of 1 txs. txs_with_safe_events=1, mismatched_txs=1, "
            "traces_deleted=1",
            output.getvalue(),
        )
        self.assertFalse(InternalTx.objects.filter(pk=wrong_trace.pk).exists())
        self.assertTrue(InternalTx.objects.filter(pk=indexed_execution.pk).exists())
        self.assertEqual(
            process_elements_mock.call_args.args[1], OrderedDict([(tx_hash, traces)])
        )

    # ------------------------------------------------------------------
    # Safes
    # ------------------------------------------------------------------
    def test_fix_safes(self):
        safe_address = Account.create().address

        def processed(block_number: int, nonce: int) -> InternalTxDecoded:
            """
            :return: Processed decoded tx of the Safe with its status
            """
            decoded = InternalTxDecodedFactory(
                internal_tx___from=safe_address,
                internal_tx__ethereum_tx__block=OrderedEthereumBlockFactory(
                    number=block_number
                ),
                processed=True,
            )
            SafeStatusFactory(
                address=safe_address, nonce=nonce, internal_tx=decoded.internal_tx
            )
            return decoded

        decoded_before = processed(150, 1)
        decoded_after = processed(160, 2)
        SafeLastStatusFactory(
            address=safe_address, nonce=2, internal_tx=decoded_after.internal_tx
        )
        # Before the first wrong multisig tx, kept
        right = self._executed_multisig_tx(safe_address, nonce=0, block_number=150)
        unchecked_before = self._executed_multisig_tx(
            safe_address, nonce=1, block_number=140, logs=[]
        )
        # Hash not executed in its tx and created by the indexer
        wrong = self._executed_multisig_tx(
            safe_address, nonce=2, logged=False, block_number=160
        )
        MultisigConfirmationFactory(multisig_transaction=wrong)
        # Hash not executed in its tx and proposed by a user
        proposed = self._executed_multisig_tx(
            safe_address,
            nonce=3,
            logged=False,
            block_number=170,
            origin={"url": "https://app"},
        )
        # After the first wrong multisig tx, processing builds it again
        unchecked_after = self._executed_multisig_tx(
            safe_address, nonce=4, block_number=180, logs=[]
        )
        right_after = self._executed_multisig_tx(
            safe_address, nonce=5, block_number=190
        )

        command, output = self._command(dry_run=True)
        command.fix_safes([safe_address, safe_address])
        self.assertIn("Checking 1 Safes", output.getvalue())
        self.assertIn(
            f"[{safe_address}] action=reset from_block=160 to_delete=2 to_unlink=1",
            output.getvalue(),
        )
        self.assertTrue(MultisigTransaction.objects.filter(pk=wrong.pk).exists())

        command, output = self._command()
        command.fix_safes([safe_address])
        self.assertIn(
            "Fixed 1 Safes. reset=1, multisig_txs_deleted=2, "
            "multisig_txs_unlinked=1, failed=0",
            output.getvalue(),
        )
        for multisig_tx in (right, unchecked_before, right_after):
            self.assertTrue(
                MultisigTransaction.objects.filter(pk=multisig_tx.pk).exists()
            )
        for multisig_tx in (wrong, unchecked_after):
            self.assertFalse(
                MultisigTransaction.objects.filter(pk=multisig_tx.pk).exists()
            )
        self.assertFalse(
            MultisigConfirmation.objects.filter(
                multisig_transaction_hash=wrong.safe_tx_hash
            ).exists()
        )
        proposed.refresh_from_db()
        self.assertIsNone(proposed.ethereum_tx)
        # Processed again from the first wrong multisig tx
        self.assertFalse(SafeLastStatus.objects.filter(address=safe_address).exists())
        self.assertEqual(
            list(
                SafeStatus.objects.filter(address=safe_address).values_list(
                    "nonce", flat=True
                )
            ),
            [1],
        )
        decoded_before.refresh_from_db()
        self.assertTrue(decoded_before.processed)
        decoded_after.refresh_from_db()
        self.assertFalse(decoded_after.processed)
        # The lock of the Safe is released
        self.assertFalse(get_redis().lock(_safe_lock_name(safe_address)).locked())

        # Nothing left to fix
        command, output = self._command()
        command.fix_safes([safe_address])
        self.assertIn(
            f"[{safe_address}] action=ok from_block=None to_delete=0 to_unlink=0",
            output.getvalue(),
        )

    def test_fix_safes_default_safes(self):
        # Repeated nonce: processed again from the first multisig tx of the nonce
        repeated = Account.create().address
        self._executed_multisig_tx(repeated, nonce=0, block_number=500)
        self._executed_multisig_tx(repeated, nonce=0, block_number=400, logs=[])
        # Same nonce but not executed, it is a proposal
        fine = Account.create().address
        self._executed_multisig_tx(fine, nonce=0, block_number=160)
        MultisigTransactionFactory(safe=fine, nonce=0, ethereum_tx=None)
        # Wrong hash in the range
        wrong_in_range = Account.create().address
        self._executed_multisig_tx(
            wrong_in_range, nonce=0, logged=False, block_number=160
        )
        banned = Account.create().address
        SafeContractFactory(address=banned, banned=True)
        self._executed_multisig_tx(banned, nonce=0, logged=False, block_number=160)
        # Wrong hash out of the range, not found
        wrong_out_of_range = Account.create().address
        self._executed_multisig_tx(
            wrong_out_of_range, nonce=0, logged=False, block_number=500
        )

        command, output = self._command(dry_run=True)
        command.fix_safes(None)
        self.assertIn("Checking 3 Safes", output.getvalue())
        self.assertIn(
            f"[{repeated}] action=reset from_block=400 to_delete=1 to_unlink=0",
            output.getvalue(),
        )
        self.assertIn(
            f"[{wrong_in_range}] action=reset from_block=160 to_delete=1",
            output.getvalue(),
        )
        self.assertIn(f"[{banned}] action=skip-banned", output.getvalue())
        self.assertNotIn(fine, output.getvalue())
        self.assertNotIn(wrong_out_of_range, output.getvalue())

        # Waves: only one Safe is changed per run
        command, output = self._command(max_safes=1)
        command.fix_safes(None)
        self.assertIn("Reached --max-safes=1", output.getvalue())
        self.assertIn("Fixed 1 Safes", output.getvalue())

        # The wrong rows of the fixed Safe are deleted, the next run continues
        command, output = self._command()
        command.fix_safes(None)
        self.assertIn("Checking 2 Safes", output.getvalue())
        self.assertIn("Fixed 1 Safes", output.getvalue())
        command, output = self._command()
        command.fix_safes(None)
        self.assertIn("Checking 1 Safes", output.getvalue())
        self.assertIn(f"[{banned}] action=skip-banned", output.getvalue())

    @mock.patch(f"{MODULE}.get_redis")
    def test_fix_safes_lock(self, get_redis_mock: MagicMock):
        locked = Account.create().address
        locked_wrong = self._executed_multisig_tx(locked, nonce=0, logged=False)
        free = Account.create().address
        free_wrong = self._executed_multisig_tx(free, nonce=0, logged=False)
        lock_mock = get_redis_mock.return_value.lock
        released: list[bool] = []

        def acquire(*args):
            if lock_mock.call_args.args[0] == _safe_lock_name(locked):
                raise LockError("Locked by a worker")
            return lock_mock.return_value

        def release(*args) -> bool:
            # The Safe is changed before releasing its lock
            released.append(
                MultisigTransaction.objects.filter(pk=free_wrong.pk).exists()
            )
            return False

        lock_mock.return_value.__enter__.side_effect = acquire
        lock_mock.return_value.__exit__.side_effect = release

        command, output = self._command()
        command.fix_safes([locked, free])
        self.assertIn(
            f"[{locked}] Cannot hold its lock: Locked by a worker", output.getvalue()
        )
        self.assertIn(f"Safe not fixed, run again: {locked}", output.getvalue())
        self.assertIn("Fixed 1 Safes", output.getvalue())
        self.assertIn("failed=1", output.getvalue())
        self.assertTrue(MultisigTransaction.objects.filter(pk=locked_wrong.pk).exists())
        self.assertFalse(MultisigTransaction.objects.filter(pk=free_wrong.pk).exists())
        self.assertEqual(released, [False])
        lock_mock.assert_called_with(
            _safe_lock_name(free),
            timeout=SAFE_LOCK_TIMEOUT,
            blocking_timeout=LOCK_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # End to end
    # ------------------------------------------------------------------
    def test_fix_safe_end_to_end(self):
        """
        A Safe processed with a wrong nonce is fixed and processed again by the
        regular processing
        """
        index_service = IndexServiceProvider()
        safe_address = Account.create().address
        master_copy = SafeMasterCopyFactory(version="1.3.0").address
        safe_call = {
            "internal_tx___from": safe_address,
            "internal_tx__to": master_copy,
            "internal_tx__value": 0,
        }
        InternalTxDecodedFactory(
            function_name="setup",
            internal_tx__ethereum_tx__block=OrderedEthereumBlockFactory(number=50),
            **safe_call,
        )
        # 2 executions of the same tx data, so only the nonce changes the hash
        executions = [
            InternalTxDecodedFactory(
                function_name="execTransaction",
                internal_tx__ethereum_tx__block=OrderedEthereumBlockFactory(
                    number=block_number
                ),
                **safe_call,
            )
            for block_number in (150, 160)
        ]
        index_service.process_decoded_txs_for_safe(safe_address)
        first, second = MultisigTransaction.objects.filter(safe=safe_address).order_by(
            "nonce"
        )
        for multisig_tx in (first, second):
            multisig_tx.ethereum_tx.logs = [
                _execution_success_log(safe_address, multisig_tx.safe_tx_hash)
            ]
            multisig_tx.ethereum_tx.save(update_fields=["logs"])
        second_tx = second.ethereum_tx
        second_safe_tx_hash = second.safe_tx_hash

        # The second execution was processed with a wrong nonce
        second.delete()
        wrong = MultisigTransactionFactory(
            safe=safe_address,
            nonce=5,
            ethereum_tx=second_tx,
            created=second_tx.block.timestamp,
            origin={},
            proposer=None,
        )
        proposed = MultisigTransactionFactory(
            safe=safe_address,
            nonce=7,
            ethereum_tx=first.ethereum_tx,
            origin={"url": "https://app"},
        )
        SafeLastStatus.objects.filter(address=safe_address).update(nonce=6)

        command, output = self._command()
        command.fix_safes([safe_address])
        self.assertIn(
            f"[{safe_address}] action=reset from_block=150 to_delete=1 to_unlink=1",
            output.getvalue(),
        )
        for execution in executions:
            execution.refresh_from_db()
            self.assertFalse(execution.processed)

        # Regular processing from the last status before the first wrong multisig tx
        index_service.process_decoded_txs_for_safe(safe_address)
        self.assertEqual(SafeLastStatus.objects.get(address=safe_address).nonce, 2)
        executed = MultisigTransaction.objects.executed().filter(safe=safe_address)
        self.assertEqual(
            {(tx.nonce, tx.ethereum_tx_id) for tx in executed},
            {(0, first.ethereum_tx_id), (1, second_tx.tx_hash)},
        )
        self.assertIn(first, executed)
        self.assertEqual(executed.get(nonce=1).safe_tx_hash, second_safe_tx_hash)
        self.assertFalse(MultisigTransaction.objects.filter(pk=wrong.pk).exists())
        proposed.refresh_from_db()
        self.assertIsNone(proposed.ethereum_tx)

        # The Safe is right now
        command, output = self._command()
        command.fix_safes([safe_address])
        self.assertIn(f"[{safe_address}] action=ok", output.getvalue())
