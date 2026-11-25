# SPDX-License-Identifier: FSL-1.1-MIT
import os.path
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.core.management import CommandError, call_command
from django.db.models import Min
from django.db.models.signals import post_save
from django.test import TestCase, override_settings
from django.utils import timezone

import factory
from django_celery_beat.models import PeriodicTask
from eth_account import Account
from hexbytes import HexBytes
from safe_eth.eth.account_abstraction import BundlerClient
from safe_eth.eth.ethereum_client import EthereumClient, EthereumNetwork
from safe_eth.eth.utils import fast_keccak_text
from safe_eth.safe import Safe
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from ...events.services.queue_service import QueueService
from ..indexers import Erc20EventsIndexer, InternalTxIndexer, SafeEventsIndexer
from ..management.commands.setup_service import Command
from ..models import (
    EthereumTx,
    IndexingStatus,
    InternalTxDecoded,
    MultisigConfirmation,
    MultisigTransaction,
    ProxyFactory,
    SafeLastStatus,
    SafeMasterCopy,
    TransactionServiceEventType,
)
from ..services import IndexServiceProvider
from ..tasks import logger as task_logger
from .factories import (
    EthereumTxFactory,
    InternalTxDecodedFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
)
from .utils import get_sent_event_types


class TestCommands(SafeTestCaseMixin, TestCase):
    def test_bind_confirmations(self):
        """
        Only unbound confirmations made on the transaction's Safe are bound to it
        """
        with factory.django.mute_signals(post_save):
            multisig_tx = MultisigTransactionFactory(ethereum_tx=None)
            same_safe_confirmation = MultisigConfirmationFactory(
                multisig_transaction=None,
                multisig_transaction_hash=multisig_tx.safe_tx_hash,
                safe_address=multisig_tx.safe,
            )
            other_safe_confirmation = MultisigConfirmationFactory(
                multisig_transaction=None,
                multisig_transaction_hash=multisig_tx.safe_tx_hash,
                safe_address=Account.create().address,
            )

        buf = StringIO()
        call_command("bind_confirmations", stdout=buf)

        same_safe_confirmation.refresh_from_db()
        self.assertEqual(
            same_safe_confirmation.multisig_transaction_id, multisig_tx.safe_tx_hash
        )
        other_safe_confirmation.refresh_from_db()
        self.assertIsNone(other_safe_confirmation.multisig_transaction_id)
        self.assertEqual(buf.getvalue().count("Bind confirmation"), 1)

    def _create_approve_hash(
        self,
        safe_address: str,
        approved_hash: str,
        owner: str | None = None,
        ethereum_tx: EthereumTx | None = None,
        trace_address: str = "0",
    ) -> EthereumTx:
        """
        Store a decoded ``approveHash`` called on ``safe_address``, with the owner in
        the arguments like the L2 events indexer, or without it like the L1 traces

        :return: Ethereum tx of the approval
        """
        arguments = {"hashToApprove": approved_hash}
        if owner:
            arguments["owner"] = owner
        extra_fields = {"internal_tx__ethereum_tx": ethereum_tx} if ethereum_tx else {}
        return InternalTxDecodedFactory(
            function_name="approveHash",
            arguments=arguments,
            internal_tx___from=safe_address,
            internal_tx__trace_address=trace_address,
            internal_tx__value=0,
            **extra_fields,
        ).internal_tx.ethereum_tx

    def _create_approval_without_safe_address(
        self, approved_hash: str, owner: str, ethereum_tx: EthereumTx, **kwargs
    ) -> MultisigConfirmation:
        with factory.django.mute_signals(post_save):
            return MultisigConfirmationFactory(
                multisig_transaction_hash=approved_hash,
                owner=owner,
                ethereum_tx=ethereum_tx,
                safe_address=None,
                signature_type=SafeSignatureType.APPROVED_HASH.value,
                **kwargs,
            )

    def test_backfill_multisig_confirmation_safe_address_fills_safe_address(self):
        """
        Approvals stored without Safe take the Safe where ``approveHash`` was called
        in their ethereum tx. Approvals with no matching call, or approved on several
        Safes, are skipped, and other confirmations are not read
        """
        safe_address = Account.create().address
        l1_owner = Account.create().address
        l2_owner = Account.create().address
        l1_hash = to_0x_hex_str(fast_keccak_text("l1-approval"))
        l2_hash = to_0x_hex_str(fast_keccak_text("l2-approval"))
        l1_ethereum_tx = self._create_approve_hash(safe_address, l1_hash)
        l2_ethereum_tx = self._create_approve_hash(
            safe_address, l2_hash, owner=l2_owner
        )
        # Same hash approved by another owner on another Safe: not ambiguous on L2
        self._create_approve_hash(
            Account.create().address,
            l2_hash,
            owner=Account.create().address,
            ethereum_tx=l2_ethereum_tx,
            trace_address="1",
        )
        l1_approval = self._create_approval_without_safe_address(
            l1_hash, l1_owner, l1_ethereum_tx, multisig_transaction=None
        )
        l2_approval = self._create_approval_without_safe_address(
            l2_hash, l2_owner, l2_ethereum_tx, multisig_transaction=None
        )
        not_found_approval = self._create_approval_without_safe_address(
            to_0x_hex_str(fast_keccak_text("not-approved")),
            l1_owner,
            l1_ethereum_tx,
            multisig_transaction=None,
        )
        ambiguous_hash = to_0x_hex_str(fast_keccak_text("ambiguous"))
        ambiguous_ethereum_tx = self._create_approve_hash(safe_address, ambiguous_hash)
        self._create_approve_hash(
            Account.create().address,
            ambiguous_hash,
            ethereum_tx=ambiguous_ethereum_tx,
            trace_address="1",
        )
        ambiguous_approval = self._create_approval_without_safe_address(
            ambiguous_hash, l1_owner, ambiguous_ethereum_tx, multisig_transaction=None
        )
        with factory.django.mute_signals(post_save):
            eoa_confirmation = MultisigConfirmationFactory(
                multisig_transaction=None,
                ethereum_tx=l1_ethereum_tx,
                safe_address=None,
                signature_type=SafeSignatureType.EOA.value,
            )

        buf = StringIO()
        call_command(
            "backfill_multisig_confirmation_safe_address",
            "--dry-run",
            "--batch-size=2",
            stdout=buf,
        )
        self.assertIn("Found 4 approvals without Safe address", buf.getvalue())
        self.assertIn("Progress 4/4 filled=2 not_found=1 ambiguous=1", buf.getvalue())
        self.assertFalse(
            MultisigConfirmation.objects.exclude(safe_address=None).exists()
        )

        call_command(
            "backfill_multisig_confirmation_safe_address",
            "--batch-size=2",
            stdout=StringIO(),
        )
        for multisig_confirmation, expected_safe_address in (
            (l1_approval, safe_address),
            (l2_approval, safe_address),
            (not_found_approval, None),
            (ambiguous_approval, None),
            (eoa_confirmation, None),
        ):
            multisig_confirmation.refresh_from_db()
            self.assertEqual(multisig_confirmation.safe_address, expected_safe_address)

    @mock.patch.object(QueueService, "send_events")
    def test_backfill_multisig_confirmation_safe_address_fixes_bindings(
        self, send_events_mock: MagicMock
    ):
        """
        After filling the Safe address: an unbound approval made on the Safe of a
        stored transaction is bound and makes it trusted, an approval bound to a
        transaction of another Safe is unbound, and a pending transaction left with
        no valid confirmation is untrusted. Transactions with another valid
        confirmation, proposed by a delegate or executed stay trusted. An approval
        whose hash was approved on several Safes, none of them the transaction's, is
        unbound too. The dry run reports the same changes as the real run
        """
        victim_safe = Account.create().address
        other_safe = Account.create().address

        def create_transaction(**kwargs) -> MultisigTransaction:
            with factory.django.mute_signals(post_save):
                return MultisigTransactionFactory(safe=victim_safe, **kwargs)

        def approve_on(
            approving_safe: str, approved_transaction: MultisigTransaction, **kwargs
        ) -> MultisigConfirmation:
            safe_tx_hash = to_0x_hex_str(HexBytes(approved_transaction.safe_tx_hash))
            owner = Account.create().address
            return self._create_approval_without_safe_address(
                safe_tx_hash,
                owner,
                self._create_approve_hash(approving_safe, safe_tx_hash, owner=owner),
                **kwargs,
            )

        never_bound_tx = create_transaction(ethereum_tx=None, trusted=False)
        never_bound_approval = approve_on(
            victim_safe, never_bound_tx, multisig_transaction=None
        )
        exploited_tx = create_transaction(ethereum_tx=None, trusted=True)
        foreign_approval = approve_on(
            other_safe, exploited_tx, multisig_transaction=exploited_tx
        )
        signed_tx = create_transaction(ethereum_tx=None, trusted=True)
        approve_on(other_safe, signed_tx, multisig_transaction=signed_tx)
        with factory.django.mute_signals(post_save):
            MultisigConfirmationFactory(
                multisig_transaction=signed_tx,
                multisig_transaction_hash=signed_tx.safe_tx_hash,
                signature_type=SafeSignatureType.EOA.value,
            )
        delegate_tx = create_transaction(
            ethereum_tx=None,
            trusted=True,
            proposed_by_delegate=Account.create().address,
        )
        approve_on(other_safe, delegate_tx, multisig_transaction=delegate_tx)
        executed_tx = create_transaction(trusted=True)
        approve_on(other_safe, executed_tx, multisig_transaction=executed_tx)
        # Also has a valid approval that was never bound
        rescued_tx = create_transaction(ethereum_tx=None, trusted=True)
        approve_on(other_safe, rescued_tx, multisig_transaction=rescued_tx)
        approve_on(victim_safe, rescued_tx, multisig_transaction=None)
        # Traces (L1) carry no owner: the hash approved on two other Safes in the
        # same ethereum tx cannot be resolved to one Safe
        ambiguous_tx = create_transaction(ethereum_tx=None, trusted=True)
        ambiguous_hash = to_0x_hex_str(HexBytes(ambiguous_tx.safe_tx_hash))
        ambiguous_ethereum_tx = self._create_approve_hash(other_safe, ambiguous_hash)
        self._create_approve_hash(
            Account.create().address,
            ambiguous_hash,
            ethereum_tx=ambiguous_ethereum_tx,
            trace_address="1",
        )
        self._create_approval_without_safe_address(
            ambiguous_hash,
            Account.create().address,
            ambiguous_ethereum_tx,
            multisig_transaction=ambiguous_tx,
        )

        buf = StringIO()
        call_command(
            "backfill_multisig_confirmation_safe_address", "--dry-run", stdout=buf
        )
        self.assertIn(
            "Would set Safe address on 7 confirmations, bind 2 confirmations, "
            "unbind approvals from 6 transactions and untrust 2 transactions",
            buf.getvalue(),
        )
        self.assertIn(
            f"Untrusting safe-tx-hash={to_0x_hex_str(HexBytes(exploited_tx.safe_tx_hash))}",
            buf.getvalue(),
        )
        self.assertIn(
            f"Untrusting safe-tx-hash={ambiguous_hash}",
            buf.getvalue(),
        )
        self.assertNotIn(
            f"Untrusting safe-tx-hash={to_0x_hex_str(HexBytes(rescued_tx.safe_tx_hash))}",
            buf.getvalue(),
        )
        exploited_tx.refresh_from_db()
        self.assertTrue(exploited_tx.trusted)

        buf = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("backfill_multisig_confirmation_safe_address", stdout=buf)
        self.assertIn(
            "Did set Safe address on 7 confirmations, bind 2 confirmations, "
            "unbind approvals from 6 transactions and untrust 2 transactions",
            buf.getvalue(),
        )

        never_bound_tx.refresh_from_db()
        self.assertTrue(never_bound_tx.trusted)
        bound_approval = MultisigConfirmation.objects.get(
            multisig_transaction_hash=never_bound_tx.safe_tx_hash,
            owner=never_bound_approval.owner,
        )
        self.assertEqual(
            bound_approval.multisig_transaction_id, never_bound_tx.safe_tx_hash
        )
        self.assertEqual(bound_approval.created, never_bound_approval.created)
        self.assertIn(
            TransactionServiceEventType.PENDING_MULTISIG_TRANSACTION.name,
            get_sent_event_types(send_events_mock),
        )

        foreign_approval.refresh_from_db()
        self.assertIsNone(foreign_approval.multisig_transaction_id)
        self.assertEqual(foreign_approval.safe_address, other_safe)
        self.assertEqual(
            MultisigConfirmation.objects.with_transaction()
            .filter(signature_type=SafeSignatureType.APPROVED_HASH.value)
            .exclude(safe_address=victim_safe)
            .count(),
            0,
        )
        for multisig_transaction, expected_trusted in (
            (exploited_tx, False),
            (signed_tx, True),
            (delegate_tx, True),
            (executed_tx, True),
            (rescued_tx, True),
            (ambiguous_tx, False),
        ):
            multisig_transaction.refresh_from_db()
            self.assertEqual(multisig_transaction.trusted, expected_trusted)

        # Running it again changes nothing
        buf = StringIO()
        call_command("backfill_multisig_confirmation_safe_address", stdout=buf)
        self.assertIn(
            "Did set Safe address on 0 confirmations, bind 0 confirmations, "
            "unbind approvals from 0 transactions and untrust 0 transactions",
            buf.getvalue(),
        )

    def test_backfill_multisig_confirmation_safe_address_keeps_new_confirmation(
        self,
    ):
        """
        A transaction that gets a real confirmation after it is selected to be
        untrusted, but before it is written, stays trusted
        """
        safe_address = Account.create().address
        with factory.django.mute_signals(post_save):
            multisig_tx = MultisigTransactionFactory(
                safe=safe_address, ethereum_tx=None, trusted=True
            )
        safe_tx_hash = to_0x_hex_str(HexBytes(multisig_tx.safe_tx_hash))
        owner = Account.create().address
        self._create_approval_without_safe_address(
            safe_tx_hash,
            owner,
            self._create_approve_hash(
                Account.create().address, safe_tx_hash, owner=owner
            ),
            multisig_transaction=multisig_tx,
        )

        class StdoutAddingConfirmation(StringIO):
            """
            Stores the owner's signature when the command reports the
            transaction it is going to untrust, like a request served meanwhile
            """

            def write(self, text: str) -> int:
                if text.startswith("Untrusting"):
                    with factory.django.mute_signals(post_save):
                        MultisigConfirmationFactory(
                            multisig_transaction=multisig_tx,
                            multisig_transaction_hash=multisig_tx.safe_tx_hash,
                            signature_type=SafeSignatureType.EOA.value,
                        )
                return super().write(text)

        buf = StdoutAddingConfirmation()
        call_command(
            "backfill_multisig_confirmation_safe_address", "--no-color", stdout=buf
        )

        self.assertIn(f"Untrusting safe-tx-hash={safe_tx_hash}", buf.getvalue())
        self.assertIn(
            "1 transactions got a confirmation while running and stay trusted",
            buf.getvalue(),
        )
        self.assertIn("untrust 0 transactions", buf.getvalue())
        multisig_tx.refresh_from_db()
        self.assertTrue(multisig_tx.trusted)

    @mock.patch.object(EthereumClient, "get_network", autospec=True)
    def _test_setup_service(
        self,
        ethereum_network: EthereumNetwork,
        ethereum_client_get_network_mock: MagicMock,
    ):
        command = "setup_service"
        ethereum_client_get_network_mock.return_value = ethereum_network
        buf = StringIO()
        self.assertEqual(SafeMasterCopy.objects.count(), 0)
        self.assertEqual(ProxyFactory.objects.count(), 0)
        self.assertEqual(PeriodicTask.objects.count(), 0)

        call_command(command, stdout=buf)
        self.assertIn(
            f"Setting up {ethereum_network.name} safe addresses", buf.getvalue()
        )
        self.assertIn(
            f"Setting up {ethereum_network.name} proxy factory addresses",
            buf.getvalue(),
        )
        self.assertIn("Created Periodic Task", buf.getvalue())
        self.assertNotIn("was already created", buf.getvalue())
        self.assertGreater(SafeMasterCopy.objects.count(), 0)
        self.assertGreater(ProxyFactory.objects.count(), 0)
        self.assertGreater(PeriodicTask.objects.count(), 0)

        # Check last master copy was created
        last_master_copy_address = "0x41675C099F32341bf84BFc5382aF534df5C7461a"
        last_master_copy = SafeMasterCopy.objects.get(address=last_master_copy_address)
        self.assertGreater(last_master_copy.initial_block_number, 0)
        self.assertGreater(last_master_copy.tx_block_number, 0)

        # Check last proxy factory was created
        last_proxy_factory_address = "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67"
        last_proxy_factory = ProxyFactory.objects.get(
            address=last_proxy_factory_address
        )
        self.assertGreater(last_proxy_factory.initial_block_number, 0)
        self.assertGreater(last_proxy_factory.tx_block_number, 0)

        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn(
            f"Setting up {ethereum_network.name} safe addresses", buf.getvalue()
        )
        self.assertIn(
            f"Setting up {ethereum_network.name} proxy factory addresses",
            buf.getvalue(),
        )
        self.assertIn("Removing old tasks", buf.getvalue())
        self.assertIn("Old tasks were removed", buf.getvalue())
        self.assertIn("Created Periodic Task", buf.getvalue())

    def test_index_erc20(self):
        command = "index_erc20"
        buf = StringIO()
        with self.assertLogs(logger=task_logger) as cm:
            call_command(command, stdout=buf)
            self.assertIn("No addresses to process", cm.output[0])

        buf = StringIO()
        call_command(command, "--block-process-limit=10", stdout=buf)
        self.assertIn("Setting block-process-limit to 10", buf.getvalue())

        buf = StringIO()
        call_command(
            command,
            "--block-process-limit=10",
            "--block-process-limit-max=15",
            stdout=buf,
        )
        self.assertIn("Setting block-process-limit to 10", buf.getvalue())
        self.assertIn("Setting block-process-limit-max to 15", buf.getvalue())

        with self.assertLogs(logger=task_logger) as cm:
            safe_contract = SafeContractFactory()
            addresses = [safe_contract.address]
            buf = StringIO()
            call_command(command, stdout=buf)
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {addresses}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

        with self.assertLogs(logger=task_logger) as cm:
            safe_contract_2 = SafeContractFactory()
            addresses = [safe_contract_2.address]
            buf = StringIO()
            call_command(command, f"--addresses={safe_contract_2.address}", stdout=buf)
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {addresses}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

        # Test sync task call
        with self.assertLogs(logger=task_logger) as cm:
            safe_contract_2 = SafeContractFactory()
            addresses = [safe_contract_2.address]
            buf = StringIO()
            call_command(
                command, f"--addresses={safe_contract_2.address}", "--sync", stdout=buf
            )
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {addresses}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_reindex_master_copies(self, current_block_number_mock: PropertyMock):
        logger_name = "safe_transaction_service.history.services.index_service"
        current_block_number_mock.return_value = 1000
        command = "reindex_master_copies"

        with self.assertRaisesMessage(
            CommandError,
            "--from-block-number must be set if --addresses are not provided",
        ):
            call_command(command)

        buf = StringIO()
        with self.assertLogs(logger_name, level="WARNING") as cm:
            call_command(
                command,
                "--block-process-limit=11",
                "--from-block-number=76",
                stdout=buf,
            )
            self.assertIn("Setting block-process-limit to 11", buf.getvalue())
            self.assertIn("No addresses to process", cm.output[0])

        safe_master_copy = SafeMasterCopyFactory(l2=False)
        buf = StringIO()
        with self.assertLogs(logger_name, level="INFO") as cm:
            with mock.patch.object(
                InternalTxIndexer, "find_relevant_elements", return_value=[]
            ) as find_relevant_elements_mock:
                IndexServiceProvider.del_singleton()
                from_block_number = 100
                block_process_limit = 500
                call_command(
                    command,
                    f"--block-process-limit={block_process_limit}",
                    f"--from-block-number={from_block_number}",
                    stdout=buf,
                )
                expected_addresses = [safe_master_copy.address]
                self.assertIn(
                    f"Start reindexing addresses {expected_addresses}",
                    cm.output[0],
                )
                self.assertIn("found 0 traces/events", cm.output[1])
                self.assertIn(
                    f"End reindexing addresses {expected_addresses}",
                    cm.output[3],
                )
                find_relevant_elements_mock.assert_any_call(
                    {safe_master_copy.address},
                    from_block_number,
                    from_block_number + block_process_limit - 1,
                )
                find_relevant_elements_mock.assert_any_call(
                    {safe_master_copy.address},
                    from_block_number + block_process_limit,
                    current_block_number_mock.return_value,
                )
                self.assertEqual(find_relevant_elements_mock.call_count, 2)

        with self.settings(ETH_L2_NETWORK=True):
            IndexServiceProvider.del_singleton()
            buf = StringIO()
            with self.assertLogs(logger_name, level="WARNING") as cm:
                call_command(command, "--from-block-number=71", stdout=buf)
                self.assertIn("No addresses to process", cm.output[0])

            with self.assertLogs(logger_name, level="INFO") as cm:
                with mock.patch.object(
                    SafeEventsIndexer, "find_relevant_elements", return_value=[]
                ) as find_relevant_elements_mock:
                    safe_l2_master_copy = SafeMasterCopyFactory(l2=True)
                    buf = StringIO()
                    from_block_number = 200
                    block_process_limit = 500
                    call_command(
                        command,
                        f"--block-process-limit={block_process_limit}",
                        f"--from-block-number={from_block_number}",
                        stdout=buf,
                    )
                    expected_addresses = [safe_l2_master_copy.address]
                    self.assertIn(
                        f"Start reindexing addresses {expected_addresses}",
                        cm.output[0],
                    )
                    self.assertIn("found 0 traces/events", cm.output[1])
                    self.assertIn(
                        f"End reindexing addresses {expected_addresses}",
                        cm.output[3],
                    )
                    find_relevant_elements_mock.assert_any_call(
                        {safe_l2_master_copy.address},
                        from_block_number,
                        from_block_number + block_process_limit - 1,
                    )
                    find_relevant_elements_mock.assert_any_call(
                        {safe_l2_master_copy.address},
                        from_block_number + block_process_limit,
                        current_block_number_mock.return_value,
                    )
                    self.assertEqual(find_relevant_elements_mock.call_count, 2)

        # Test without --from-block-number
        with self.settings(ETH_L2_NETWORK=True):
            IndexServiceProvider.del_singleton()
            with self.assertLogs(logger_name, level="INFO") as cm:
                with mock.patch.object(
                    SafeEventsIndexer, "find_relevant_elements", return_value=[]
                ) as find_relevant_elements_mock:
                    safe_l2_master_copy = SafeMasterCopyFactory(l2=True)
                    buf = StringIO()
                    from_block_number = 200
                    block_process_limit = 500

                    safe_address_1 = Account.create().address
                    safe_address_2 = Account.create().address
                    # Safes do not exist, so from_block_number cannot be retrieved
                    with self.assertRaisesMessage(
                        CommandError,
                        "Cannot get from-block-number, please set --from-block-number yourself",
                    ):
                        call_command(
                            command,
                            addresses=[safe_address_1, safe_address_2],
                            block_process_limit=block_process_limit,
                            stdout=buf,
                        )

                    # Create Safes on the database and try again
                    buf = StringIO()
                    SafeContractFactory(
                        address=safe_address_1, ethereum_tx__block__number=4
                    )
                    SafeContractFactory(
                        address=safe_address_2, ethereum_tx__block__number=8
                    )
                    call_command(
                        command,
                        addresses=[safe_address_1, safe_address_2],
                        block_process_limit=block_process_limit,
                        stdout=buf,
                    )
                    self.assertIn(
                        f"Start reindexing addresses ['{safe_address_1}', '{safe_address_2}']",
                        cm.output[0],
                    )
                    self.assertIn("Setting from-block-number to 4", buf.getvalue())

        IndexServiceProvider.del_singleton()

    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_reindex_master_copies_without_block_process_limit(
        self, current_block_number_mock: PropertyMock
    ):
        """
        When ``--block-process-limit`` is not provided the indexer's
        settings-derived limit must drive the first chunk (so auto-adjust
        engages from that anchor), and no "Setting block-process-limit"
        line is printed.
        """
        from django.conf import settings

        # Set high enough so the first chunk is not clamped by stop_block_number
        current_block_number_mock.return_value = 1_000_000
        safe_master_copy = SafeMasterCopyFactory(l2=False)

        buf = StringIO()
        with mock.patch.object(
            InternalTxIndexer, "find_relevant_elements", return_value=[]
        ) as find_relevant_elements_mock:
            IndexServiceProvider.del_singleton()
            from_block_number = 100
            call_command(
                "reindex_master_copies",
                f"--from-block-number={from_block_number}",
                stdout=buf,
            )
            self.assertNotIn("Setting block-process-limit", buf.getvalue())
            expected_limit = settings.ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT
            find_relevant_elements_mock.assert_any_call(
                {safe_master_copy.address},
                from_block_number,
                from_block_number + expected_limit - 1,
            )
        IndexServiceProvider.del_singleton()

    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_reindex_erc20_events(self, current_block_number_mock: PropertyMock):
        logger_name = "safe_transaction_service.history.services.index_service"
        current_block_number_mock.return_value = 1000
        command = "reindex_erc20"

        with self.assertRaisesMessage(
            CommandError,
            "--from-block-number must be set if --addresses are not provided",
        ):
            call_command(command)

        buf = StringIO()
        with self.assertLogs(logger_name, level="WARNING") as cm:
            call_command(
                command,
                "--block-process-limit=11",
                "--from-block-number=76",
                stdout=buf,
            )
            self.assertIn("Setting block-process-limit to 11", buf.getvalue())
            self.assertIn("No addresses to process", cm.output[0])

        safe_contract = SafeContractFactory()
        buf = StringIO()
        with self.assertLogs(logger_name, level="INFO") as cm:
            with mock.patch.object(
                Erc20EventsIndexer, "find_relevant_elements", return_value=[]
            ) as find_relevant_elements_mock:
                IndexServiceProvider.del_singleton()
                from_block_number = 100
                block_process_limit = 500
                call_command(
                    command,
                    f"--block-process-limit={block_process_limit}",
                    f"--from-block-number={from_block_number}",
                    stdout=buf,
                )
                expected_addresses = [safe_contract.address]
                self.assertIn(
                    f"Start reindexing addresses {expected_addresses}",
                    cm.output[0],
                )
                self.assertIn("found 0 traces/events", cm.output[1])
                self.assertIn(
                    f"End reindexing addresses {expected_addresses}",
                    cm.output[3],
                )
                # The ERC20/721 indexer reindexes with raw-bytes addresses
                find_relevant_elements_mock.assert_any_call(
                    {HexBytes(safe_contract.address)},
                    from_block_number,
                    from_block_number + block_process_limit - 1,
                )
                find_relevant_elements_mock.assert_any_call(
                    {HexBytes(safe_contract.address)},
                    from_block_number + block_process_limit,
                    current_block_number_mock.return_value,
                )
                self.assertEqual(find_relevant_elements_mock.call_count, 2)
        IndexServiceProvider.del_singleton()

    def test_setup_service_mainnet(self):
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 0
        )
        self._test_setup_service(EthereumNetwork.MAINNET)
        first_safe_block_deployed = (
            6569433  # 0.0.2 deployment block, first Safe contract
        )
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            first_safe_block_deployed,
        )

        # Check last master copy was created
        last_master_copy_address = "0x6851D6fDFAfD08c0295C392436245E5bc78B0185"
        last_master_copy_initial_block = 10329734
        last_master_copy = SafeMasterCopy.objects.get(address=last_master_copy_address)
        self.assertEqual(
            last_master_copy.initial_block_number, last_master_copy_initial_block
        )
        self.assertEqual(
            last_master_copy.tx_block_number, last_master_copy_initial_block
        )

        # Check last proxy factory was created
        last_proxy_factory_address = "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B"
        last_proxy_factory_initial_block = 9084508
        last_proxy_factory = ProxyFactory.objects.get(
            address=last_proxy_factory_address
        )
        self.assertEqual(
            last_proxy_factory.initial_block_number, last_proxy_factory_initial_block
        )
        self.assertEqual(
            last_proxy_factory.tx_block_number, last_proxy_factory_initial_block
        )

        # At Mar 2025 we support 14 Master Copies, 4 L2 Master Copies and 7 Proxy Factories
        self.assertEqual(SafeMasterCopy.objects.count(), 14)
        self.assertEqual(SafeMasterCopy.objects.l2().count(), 4)
        self.assertEqual(ProxyFactory.objects.count(), 7)

    def test_setup_service_mainnet_erc20_indexing_setup(self):
        # Test IndexingStatus ERC20 is not modified if higher than the oldest master copy
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 0
        )
        first_safe_block_deployed = (
            6569433  # 0.0.2 deployment block, first Safe contract
        )
        IndexingStatus.objects.set_erc20_721_indexing_status(
            first_safe_block_deployed + 20
        )
        self._test_setup_service(EthereumNetwork.MAINNET)
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number,
            first_safe_block_deployed + 20,
        )

    @override_settings(ETH_L2_NETWORK=True)
    def test_setup_safe_singleton_addresses_l2_frontier(self):
        """
        On an L2 network a new +L2 singleton added to an already-synced chain must start at the
        current L2 frontier (lowest tx_block_number among L2 singletons), not its deploy block, so
        it doesn't drag the shared topic-based scan window back. L1-flavour singletons still start
        from the deploy block.
        """
        # Already-synced chain: an existing L2 singleton indexed up to a high block
        existing_l2 = SafeMasterCopyFactory(
            l2=True, initial_block_number=100, tx_block_number=5000
        )
        l2_frontier = existing_l2.tx_block_number

        new_l2_address = Account.create().address
        new_l1_address = Account.create().address
        deploy_block = 4000  # Lower than the frontier

        Command()._setup_safe_singleton_addresses(
            [
                (new_l2_address, deploy_block, "1.5.0+L2"),
                (new_l1_address, deploy_block, "1.5.0"),
            ]
        )

        # New L2 singleton starts at the frontier; the real deploy block is kept as
        # initial_block_number
        new_l2 = SafeMasterCopy.objects.get(address=new_l2_address)
        self.assertEqual(new_l2.tx_block_number, l2_frontier)
        self.assertEqual(new_l2.initial_block_number, deploy_block)
        self.assertTrue(new_l2.l2)

        # The shared L2 scan window is not dragged back
        self.assertEqual(
            SafeMasterCopy.objects.l2().aggregate(m=Min("tx_block_number"))["m"],
            l2_frontier,
        )

        # L1 singleton still starts from its deploy block
        new_l1 = SafeMasterCopy.objects.get(address=new_l1_address)
        self.assertEqual(new_l1.tx_block_number, deploy_block)
        self.assertEqual(new_l1.initial_block_number, deploy_block)
        self.assertFalse(new_l1.l2)

        # Existing row is untouched
        existing_l2.refresh_from_db()
        self.assertEqual(existing_l2.tx_block_number, 5000)

    @override_settings(ETH_L2_NETWORK=True)
    def test_setup_safe_singleton_addresses_l2_fresh_db(self):
        """
        On a fresh DB (no L2 singletons yet) a new +L2 singleton starts from its deploy block.
        """
        address = Account.create().address
        deploy_block = 4000
        Command()._setup_safe_singleton_addresses([(address, deploy_block, "1.4.1+L2")])

        master_copy = SafeMasterCopy.objects.get(address=address)
        self.assertEqual(master_copy.tx_block_number, deploy_block)
        self.assertEqual(master_copy.initial_block_number, deploy_block)

    @override_settings(ETH_L2_NETWORK=True)
    def test_setup_safe_singleton_addresses_l2_below_scan_floor(self):
        """
        On an L2 network a new +L2 singleton deployed below the scan floor (its deploy block is
        lower than the lowest block ever scanned) starts from its deploy block, not the frontier,
        so events in the never-scanned gap are not missed.
        """
        # Already-synced chain that was only ever scanned from block 2000 up to 8000
        SafeMasterCopyFactory(l2=True, initial_block_number=2000, tx_block_number=8000)

        address = Account.create().address
        deploy_block = 1000  # Below the scan floor (2000)
        Command()._setup_safe_singleton_addresses([(address, deploy_block, "1.3.0+L2")])

        master_copy = SafeMasterCopy.objects.get(address=address)
        self.assertEqual(master_copy.tx_block_number, deploy_block)
        self.assertEqual(master_copy.initial_block_number, deploy_block)

    @override_settings(ETH_L2_NETWORK=True)
    def test_setup_safe_singleton_addresses_l2_deploy_ahead_of_current(self):
        """
        While the chain is still catching up, a new +L2 singleton whose deploy block is ahead of
        the current indexing position starts at its deploy block, never below it, so
        tx_block_number stays >= initial_block_number.
        """
        # Chain scanned from block 100, currently only advanced to block 5000
        SafeMasterCopyFactory(l2=True, initial_block_number=100, tx_block_number=5000)

        address = Account.create().address
        deploy_block = (
            8000  # Ahead of the current position (5000), above the floor (100)
        )
        Command()._setup_safe_singleton_addresses([(address, deploy_block, "1.5.0+L2")])

        master_copy = SafeMasterCopy.objects.get(address=address)
        self.assertEqual(master_copy.tx_block_number, deploy_block)
        self.assertEqual(master_copy.initial_block_number, deploy_block)

    @override_settings(ETH_L2_NETWORK=False)
    def test_setup_safe_singleton_addresses_l1_network_keeps_deploy_block(self):
        """
        On an L1/tracing network SafeEventsIndexer is disabled and InternalTxIndexer matches
        traces by address. A +L2 singleton is tracked there too (e.g. on mainnet), so it must
        start from its deploy block even with a synced L2 row present, or its traces in
        [deploy, frontier] would never be indexed.
        """
        # An already-synced +L2 row (would-be frontier at block 5000)
        SafeMasterCopyFactory(l2=True, initial_block_number=100, tx_block_number=5000)

        address = Account.create().address
        deploy_block = 4000  # Above the floor: the L2 shortcut would wrongly pick 5000
        Command()._setup_safe_singleton_addresses([(address, deploy_block, "1.5.0+L2")])

        master_copy = SafeMasterCopy.objects.get(address=address)
        self.assertEqual(master_copy.tx_block_number, deploy_block)
        self.assertEqual(master_copy.initial_block_number, deploy_block)

    def test_setup_service_sepolia(self):
        self._test_setup_service(EthereumNetwork.SEPOLIA)

    @mock.patch.object(EthereumClient, "is_contract", return_value=False)
    @mock.patch.object(EthereumClient, "get_network", autospec=True)
    def test_setup_service_not_valid_network(
        self, ethereum_client_get_network_mock: MagicMock, is_contract_mock: MagicMock
    ):
        command = "setup_service"
        for return_value in (EthereumNetwork.ROPSTEN, EthereumNetwork.UNKNOWN):
            ethereum_client_get_network_mock.return_value = return_value
            buf = StringIO()
            call_command(command, stdout=buf)
            self.assertIn(
                "Cannot find any SafeMasterCopy and ProxyFactory for chain id",
                buf.getvalue(),
            )

    @mock.patch.object(EthereumClient, "get_network", autospec=True)
    def test_setup_service_without_addresses(
        self, ethereum_client_get_network_mock: MagicMock
    ):
        """
        Test setup_service without any SafeSingleton and ProxyFactory added on safe-eth-py.
        Setup service command should check if any of the default addresses is a contract on chain and add them.
        """
        command = "setup_service"
        ethereum_network = EthereumNetwork.GANACHE
        ethereum_client_get_network_mock.return_value = ethereum_network
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertNotIn(
            "Cannot find any SafeMasterCopy and ProxyFactory for chain id",
            buf.getvalue(),
        )
        self.assertIn(
            f"Setting up {ethereum_network.name} default safe addresses from chain with unknown init block",
            buf.getvalue(),
        )
        self.assertEqual(SafeMasterCopy.objects.count(), 3)
        self.assertEqual(ProxyFactory.objects.count(), 2)

    @mock.patch.object(EthereumClient, "get_network", autospec=True)
    def test_setup_service_update_singletons(
        self, ethereum_client_get_network_mock: MagicMock
    ):
        """
        Test if version or initial block_number is being updated when safe_eth_py contains different version or
        intial_block_number than the database values.
        """
        command = "setup_service"
        ethereum_network = EthereumNetwork.GANACHE
        ethereum_client_get_network_mock.return_value = ethereum_network
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertEqual(SafeMasterCopy.objects.count(), 3)
        # Both v1.5.0 and v1.4.1 proxy factories exist in test environment
        # v1.5.0: 0x14F2982D601c9458F93bd70B218933A6f8165e7b (deployed by SafeTestCaseMixin)
        # v1.4.1: 0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67 (deployed via Singleton Factory)
        self.assertEqual(ProxyFactory.objects.count(), 2)
        master_copy = SafeMasterCopy.objects.first()
        self.assertEqual(master_copy.initial_block_number, 0)
        mocked_addresses = {ethereum_network: [(master_copy.address, 111, "v1.1.1")]}

        with mock.patch(
            "safe_transaction_service.history.management.commands.setup_service.MASTER_COPIES",
            new=mocked_addresses,
        ):
            buf = StringIO()
            call_command(command, stdout=buf)
            master_copy_updated = SafeMasterCopy.objects.get(
                address=master_copy.address
            )
            self.assertEqual(master_copy_updated.initial_block_number, 111)
            self.assertEqual(master_copy_updated.version, "v1.1.1")

    def test_export_multisig_tx_data(self):
        with tempfile.TemporaryDirectory() as tmpdirname:
            command = "export_multisig_tx_data"
            arguments = "--file-name=" + os.path.join(tmpdirname, "result.csv")
            buf = StringIO()
            call_command(command, arguments, stdout=buf)
            self.assertIn("Start exporting of 0", buf.getvalue())

            MultisigTransactionFactory(origin="something")
            MultisigTransactionFactory(
                origin="another-something", ethereum_tx=None
            )  # Will not be exported
            MultisigTransactionFactory(origin={})  # Will not be exported
            buf = StringIO()
            call_command(command, arguments, stdout=buf)
            self.assertIn("Start exporting of 1", buf.getvalue())

    @mock.patch(
        "safe_transaction_service.history.management.commands.check_chainid_matches.get_bundler_client",
        return_value=None,
    )
    @mock.patch(
        "safe_transaction_service.history.management.commands.check_chainid_matches.get_chain_id"
    )
    def test_check_chainid_matches(
        self, get_chain_id_mock: MagicMock, get_bundler_client_mock: MagicMock
    ):
        command = "check_chainid_matches"

        # Create ChainId model
        get_chain_id_mock.return_value = EthereumNetwork.MAINNET.value
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("EthereumRPC chainId 1 looks good", buf.getvalue())

        # Use different chainId
        get_chain_id_mock.return_value = EthereumNetwork.GNOSIS.value
        with self.assertRaisesMessage(
            CommandError,
            "EthereumRPC chainId 100 does not match previously used chainId 1",
        ):
            call_command(command)

        # Check again with the initial chainId
        get_chain_id_mock.return_value = EthereumNetwork.MAINNET.value
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("EthereumRPC chainId 1 looks good", buf.getvalue())

    @mock.patch.object(BundlerClient, "get_chain_id", return_value=1234)
    @mock.patch(
        "safe_transaction_service.history.management.commands.check_chainid_matches.get_bundler_client",
        return_value=BundlerClient(""),
    )
    @mock.patch(
        "safe_transaction_service.history.management.commands.check_chainid_matches.get_chain_id",
        return_value=EthereumNetwork.MAINNET.value,
    )
    def test_check_chainid_bundler_matches(
        self,
        get_chain_id_mock: MagicMock,
        get_bundler_client_mock: MagicMock,
        bundler_get_chain_id_mock: MagicMock,
    ):
        command = "check_chainid_matches"
        with self.assertRaisesMessage(
            CommandError,
            "ERC4337 BundlerClient chainId 1234 does not match EthereumClient chainId 1",
        ):
            call_command(command)

        bundler_get_chain_id_mock.return_value = EthereumNetwork.MAINNET.value
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertEqual(
            "EthereumRPC chainId 1 looks good\nERC4337 BundlerClient chainId 1 looks good\n",
            buf.getvalue(),
        )

    @mock.patch(
        "safe_transaction_service.history.management.commands.check_index_problems.settings.ETH_L2_NETWORK",
        return_value=True,
    )
    def test_check_index_problems(self, mock_eth_l2_network: MagicMock):
        command = "check_index_problems"
        buf = StringIO()
        # Test empty with empty SafeContract model
        call_command(command, stdout=buf)
        self.assertIn("Database haven't any address to be checked", buf.getvalue())

        # Should ignore Safe with nonce 0
        owner = Account.create()
        safe = self.deploy_test_safe(
            number_owners=1,
            threshold=1,
            owners=[owner.address],
            initial_funding_wei=1000,
        )
        SafeContractFactory(address=safe.address)
        SafeLastStatusFactory(nonce=0, address=safe.address)
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Database haven't any address to be checked", buf.getvalue())

        # Should detect missing transactions
        data = b""
        value = 122
        to = Account.create().address
        multisig_tx = safe.build_multisig_tx(to, value, data)
        multisig_tx.sign(owner.key)
        tx_hash, _ = multisig_tx.execute(self.ethereum_test_account.key)
        self.wait_for_receipt(tx_hash)
        SafeLastStatus.objects.filter(address=safe.address).update(nonce=1)
        self.assertEqual(InternalTxDecoded.objects.count(), 0)
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn(
            f"Safe={safe.address} is corrupted, has some old transactions missing",
            buf.getvalue(),
        )
        self.assertEqual(InternalTxDecoded.objects.count(), 1)
        with self.assertRaises(SafeLastStatus.DoesNotExist):
            SafeLastStatus.objects.get(address=safe.address)

        # Should works with batch_size option
        SafeLastStatusFactory(nonce=1, address=safe.address)
        buf = StringIO()
        call_command(command, "--batch-size=1", stdout=buf)
        self.assertIn(
            f"Safe={safe.address} is corrupted, has some old transactions missing",
            buf.getvalue(),
        )
        self.assertEqual(InternalTxDecoded.objects.count(), 1)
        with self.assertRaises(SafeLastStatus.DoesNotExist):
            SafeLastStatus.objects.get(address=safe.address)

        # Should detect incorrect nonce
        with mock.patch.object(SafeLastStatus, "is_corrupted", return_value=False):
            SafeLastStatusFactory(nonce=2, address=safe.address)
            buf = StringIO()
            call_command(command, stdout=buf)
            self.assertIn(
                f"Safe={safe.address} stored nonce=2 is different from blockchain-nonce=1",
                buf.getvalue(),
            )
            with self.assertRaises(SafeLastStatus.DoesNotExist):
                SafeLastStatus.objects.get(address=safe.address)

    def test_validate_tx_integrity(self):
        command = "validate_tx_integrity"

        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Found 0 transactions", buf.getvalue())

        account = Account.create()
        safe_last_status = SafeLastStatusFactory(nonce=0, address=account.address)
        multisig_transaction = MultisigTransactionFactory(
            ethereum_tx=None, nonce=0, safe=safe_last_status.address
        )
        multisig_confirmation = MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction
        )

        # Signatures are not valid by default
        buf = StringIO()
        call_command(command, stdout=buf)
        text = buf.getvalue()
        self.assertIn("Found 1 transactions", text)
        self.assertNotIn("should not have signatures as it is not executed", text)
        self.assertIn(f"{multisig_transaction.safe_tx_hash} is not matching", text)
        self.assertIn(
            f"Confirmation for owner {multisig_confirmation.owner} is not valid for multisig transaction {multisig_transaction.safe_tx_hash}",
            text,
        )

        # Fix confirmation signature
        multisig_confirmation.owner = account.address
        multisig_confirmation.signature = account.unsafe_sign_hash(
            multisig_transaction.safe_tx_hash
        )["signature"]
        multisig_confirmation.save(update_fields=["owner", "signature"])

        # Confirmation signature is now alright
        buf = StringIO()
        call_command(command, stdout=buf)
        text = buf.getvalue()
        self.assertIn("Found 1 transactions", text)
        self.assertNotIn("should not have signatures as it is not executed", text)
        self.assertIn(f"{multisig_transaction.safe_tx_hash} is not matching", text)
        self.assertNotIn("is not valid for multisig transaction", text)

        # Fix safeTxHash too
        safe = Safe(multisig_transaction.safe, self.ethereum_client)
        safe_tx = safe.build_multisig_tx(
            multisig_transaction.to,
            multisig_transaction.value,
            multisig_transaction.data,
            multisig_transaction.operation,
            multisig_transaction.safe_tx_gas,
            multisig_transaction.base_gas,
            multisig_transaction.gas_price,
            multisig_transaction.gas_token,
            multisig_transaction.refund_receiver,
            safe_nonce=multisig_transaction.nonce,
        )
        multisig_transaction.delete()  # When replacing primary key, a new instance will be created
        multisig_transaction.safe_tx_hash = to_0x_hex_str(safe_tx.safe_tx_hash)
        multisig_transaction.save()

        # SafeTxHash is good now
        buf = StringIO()
        call_command(command, stdout=buf)
        text = buf.getvalue()
        self.assertIn("Found 1 transactions", text)
        self.assertNotIn("should not have signatures as it is not executed", text)
        self.assertNotIn("is not matching", text)
        self.assertNotIn("is not valid for multisig transaction", text)

        # Empty signatures
        multisig_transaction.signatures = b"123456"
        multisig_transaction.save(update_fields=["signatures"])

        # Test signature not empty
        buf = StringIO()
        call_command(command, stdout=buf)
        text = buf.getvalue()
        self.assertIn("Found 1 transactions", text)
        self.assertIn(
            f"{multisig_transaction.safe_tx_hash} should not have signatures as it is not executed",
            text,
        )
        self.assertNotIn("is not matching", text)
        self.assertNotIn("is not valid for multisig transaction", text)

    def test_backfill_multisig_tx_payment(self):
        command = "backfill_multisig_tx_payment"

        # No transactions to process
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Processing 0", buf.getvalue())

        # Transaction without ethereum_tx is skipped
        MultisigTransactionFactory(ethereum_tx=None)
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Processing 0", buf.getvalue())

        # ExecutionSuccess v1.4.1 — indexed txHash in topics[1], payment in data
        safe_tx_hash = (
            "0xa3324f8210e3d1772329133a15ad3bb31b848c8ca2498e36a787982a685d2484"
        )
        ethereum_tx = EthereumTxFactory(
            logs=[
                {
                    "topics": [
                        "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e",
                        safe_tx_hash,
                    ],
                    "data": "0x0000000000000000000000000000000000000000000000000000038fc9cbcc74",
                }
            ]
        )
        multisig_tx = MultisigTransactionFactory(
            safe_tx_hash=safe_tx_hash, ethereum_tx=ethereum_tx
        )
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Processing 1", buf.getvalue())
        self.assertIn("Updated payment for 1/1", buf.getvalue())
        multisig_tx.refresh_from_db()
        self.assertEqual(multisig_tx.payment, 3916100783220)

        # Idempotent: already-set payment is not reprocessed
        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn("Processing 0", buf.getvalue())

        # ExecutionFailure v1.3.0 — unindexed txHash, payment in data
        safe_tx_hash_2 = (
            "0xb3418ba0a5d1af8a5e17b410e54f709e89ed6f45362ef772c12f70529c538ae7"
        )
        ethereum_tx_2 = EthereumTxFactory(
            logs=[
                {
                    "topics": [
                        "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23",
                    ],
                    "data": (
                        "0xb3418ba0a5d1af8a5e17b410e54f709e89ed6f45362ef772c12f70529c538ae7"
                        "0000000000000000000000000000000000000000000000000000023f62a7b29c"
                    ),
                }
            ]
        )
        multisig_tx_2 = MultisigTransactionFactory(
            safe_tx_hash=safe_tx_hash_2, ethereum_tx=ethereum_tx_2
        )

        # Wrong safe address → skipped
        buf = StringIO()
        call_command(command, f"--safe-address={Account.create().address}", stdout=buf)
        self.assertIn("Processing 0", buf.getvalue())
        multisig_tx_2.refresh_from_db()
        self.assertIsNone(multisig_tx_2.payment)

        # Correct safe address → processed
        buf = StringIO()
        call_command(command, f"--safe-address={multisig_tx_2.safe}", stdout=buf)
        self.assertIn("Processing 1", buf.getvalue())
        self.assertIn("Updated payment for 1/1", buf.getvalue())
        multisig_tx_2.refresh_from_db()
        self.assertEqual(multisig_tx_2.payment, 2471261352604)


_COMMAND = "backfill_delete_failed_ethereum_txs"
_CLIENT_PATH = "safe_transaction_service.history.management.commands.backfill_delete_failed_ethereum_txs.get_auto_ethereum_client"


class TestBackfillDeleteFailedEthereumTxsCommand(TestCase):
    def _make_client_mock(self, receipt):
        client = MagicMock()
        client.get_transaction_receipt.return_value = receipt
        mock_provider = MagicMock(return_value=client)
        return mock_provider, client

    @mock.patch(_CLIENT_PATH)
    def test_deletes_tx_with_failed_receipt(self, mock_provider):
        client = MagicMock()
        client.get_transaction_receipt.return_value = {"status": 0}
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        buf = StringIO()
        call_command(_COMMAND, stdout=buf)

        self.assertFalse(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("Deleted 1/1", buf.getvalue())

    @mock.patch(_CLIENT_PATH)
    def test_keeps_tx_with_successful_receipt(self, mock_provider):
        client = MagicMock()
        client.get_transaction_receipt.return_value = {"status": 1}
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        buf = StringIO()
        call_command(_COMMAND, stdout=buf)

        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("Deleted 0/1", buf.getvalue())

    @mock.patch(_CLIENT_PATH)
    def test_skips_tx_with_missing_receipt(self, mock_provider):
        client = MagicMock()
        client.get_transaction_receipt.return_value = None
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        buf = StringIO()
        call_command(_COMMAND, stdout=buf)

        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("missing_receipts=1", buf.getvalue())

    @mock.patch(_CLIENT_PATH)
    def test_dry_run_does_not_delete(self, mock_provider):
        client = MagicMock()
        client.get_transaction_receipt.return_value = {"status": 0}
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        buf = StringIO()
        call_command(_COMMAND, "--dry-run", stdout=buf)

        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("Would delete 1/1", buf.getvalue())

    @mock.patch("time.sleep")
    @mock.patch(_CLIENT_PATH)
    def test_retries_on_rpc_error_then_succeeds(self, mock_provider, mock_sleep):
        client = MagicMock()
        client.get_transaction_receipt.side_effect = [
            Exception("timeout"),
            {"status": 0},
        ]
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        buf = StringIO()
        call_command(_COMMAND, "--retries=2", "--backoff=0", stdout=buf)

        self.assertFalse(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("Deleted 1/1", buf.getvalue())
        mock_sleep.assert_called_once_with(0.0)

    @mock.patch("time.sleep")
    @mock.patch(_CLIENT_PATH)
    def test_skips_tx_after_exhausted_retries(self, mock_provider, mock_sleep):
        client = MagicMock()
        client.get_transaction_receipt.side_effect = Exception("timeout")
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        buf = StringIO()
        call_command(_COMMAND, "--retries=3", "--backoff=0", stdout=buf)

        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("rpc_errors=1", buf.getvalue())
        self.assertEqual(client.get_transaction_receipt.call_count, 3)

    @mock.patch(_CLIENT_PATH)
    def test_days_filter_excludes_old_txs(self, mock_provider):
        client = MagicMock()
        client.get_transaction_receipt.return_value = {"status": 0}
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        EthereumTx.objects.filter(tx_hash=tx.tx_hash).update(
            created=timezone.now() - timedelta(days=40)
        )

        buf = StringIO()
        call_command(_COMMAND, "--days=30", stdout=buf)

        self.assertTrue(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("Checking 0 EthereumTx rows", buf.getvalue())

    @mock.patch(_CLIENT_PATH)
    def test_no_days_includes_all_txs(self, mock_provider):
        client = MagicMock()
        client.get_transaction_receipt.return_value = {"status": 0}
        mock_provider.return_value = client

        tx = EthereumTxFactory(status=1)
        EthereumTx.objects.filter(tx_hash=tx.tx_hash).update(
            created=timezone.now() - timedelta(days=365)
        )

        buf = StringIO()
        call_command(_COMMAND, stdout=buf)

        self.assertFalse(EthereumTx.objects.filter(tx_hash=tx.tx_hash).exists())
        self.assertIn("all time", buf.getvalue())
