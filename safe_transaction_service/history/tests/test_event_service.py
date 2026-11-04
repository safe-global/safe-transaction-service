# SPDX-License-Identifier: FSL-1.1-MIT
import dataclasses
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes
from safe_eth.eth import EthereumNetwork
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.util.util import to_0x_hex_str

from ..models import TransactionServiceEventType
from ..services.event_service import (
    SafeConfigSnapshot,
    build_safe_config_payloads,
    take_safe_config_snapshot,
)
from .factories import InternalTxFactory, SafeLastStatusFactory


class TestBuildSafeConfigPayloads(TestCase):
    def setUp(self):
        self.safe_address = Account.create().address
        self.internal_tx = InternalTxFactory(_from=self.safe_address)
        self.before = SafeConfigSnapshot(
            owners=[Account.create().address, Account.create().address],
            threshold=1,
            nonce=5,
            master_copy=Account.create().address,
            fallback_handler=NULL_ADDRESS,
            guard=NULL_ADDRESS,
            module_guard=NULL_ADDRESS,
            enabled_modules=[Account.create().address],
        )

    def build_payloads(self, **changes) -> list[dict]:
        """
        :param changes: Fields of ``self.before`` changed by the decoded tx
        :return: Payloads for the changes
        """
        after = dataclasses.replace(self.before, **changes)
        safe_status = SafeLastStatusFactory.build(
            address=self.safe_address, **dataclasses.asdict(after)
        )
        return build_safe_config_payloads(self.before, self.internal_tx, safe_status)

    def assert_changes(self, payloads: list[dict], expected: list[tuple[str, dict]]):
        self.assertEqual(
            [(payload["change"], payload["data"]) for payload in payloads], expected
        )

    def test_no_changes(self):
        """
        No payloads are built when the configuration did not change.
        """
        self.assertEqual(self.build_payloads(), [])

    def test_nonce_is_not_a_config_change(self):
        """
        A nonce change alone builds no payloads.
        """
        self.assertEqual(self.build_payloads(nonce=self.before.nonce + 1), [])

    def test_payload(self):
        """
        Full shape of a ``SAFE_CONFIG_UPDATED`` payload.
        """
        new_owner = Account.create().address
        self.assertEqual(
            self.build_payloads(owners=[new_owner] + self.before.owners),
            [
                {
                    "timestamp": int(self.internal_tx.timestamp.timestamp()),
                    "address": self.safe_address,
                    "type": TransactionServiceEventType.SAFE_CONFIG_UPDATED.name,
                    "txHash": to_0x_hex_str(HexBytes(self.internal_tx.ethereum_tx_id)),
                    "change": "ADDED_OWNER",
                    "data": {"owner": new_owner},
                    "status": {
                        "owners": [new_owner] + self.before.owners,
                        "threshold": self.before.threshold,
                        "nonce": self.before.nonce,
                        "enabledModules": self.before.enabled_modules,
                        "guard": NULL_ADDRESS,
                        "moduleGuard": NULL_ADDRESS,
                        "fallbackHandler": NULL_ADDRESS,
                        "masterCopy": self.before.master_copy,
                    },
                    "chainId": str(EthereumNetwork.GANACHE.value),
                }
            ],
        )

    def test_swap_owner(self):
        """
        A swapped owner builds ``REMOVED_OWNER`` and then ``ADDED_OWNER``.
        """
        old_owner = self.before.owners[0]
        new_owner = Account.create().address
        self.assert_changes(
            self.build_payloads(owners=[new_owner, self.before.owners[1]]),
            [
                ("REMOVED_OWNER", {"owner": old_owner}),
                ("ADDED_OWNER", {"owner": new_owner}),
            ],
        )

    def test_owner_and_threshold(self):
        """
        An owner added with a new threshold builds both changes with the same status.
        """
        new_owner = Account.create().address
        payloads = self.build_payloads(
            owners=[new_owner] + self.before.owners, threshold=2
        )
        self.assert_changes(
            payloads,
            [
                ("ADDED_OWNER", {"owner": new_owner}),
                ("CHANGED_THRESHOLD", {"threshold": 2}),
            ],
        )
        # Every payload has the status after the decoded tx
        self.assertEqual(payloads[0]["status"], payloads[1]["status"])
        self.assertEqual(payloads[1]["status"]["threshold"], 2)

    def test_every_change(self):
        """
        Every kind of change is built, in a fixed order.
        """
        new_module = Account.create().address
        guard = Account.create().address
        module_guard = Account.create().address
        fallback_handler = Account.create().address
        master_copy = Account.create().address
        self.assert_changes(
            self.build_payloads(
                owners=self.before.owners[1:],
                threshold=2,
                enabled_modules=[new_module],
                guard=guard,
                module_guard=module_guard,
                fallback_handler=fallback_handler,
                master_copy=master_copy,
            ),
            [
                ("REMOVED_OWNER", {"owner": self.before.owners[0]}),
                ("CHANGED_THRESHOLD", {"threshold": 2}),
                ("DISABLED_MODULE", {"module": self.before.enabled_modules[0]}),
                ("ENABLED_MODULE", {"module": new_module}),
                ("CHANGED_GUARD", {"guard": guard}),
                ("CHANGED_MODULE_GUARD", {"moduleGuard": module_guard}),
                ("CHANGED_FALLBACK_HANDLER", {"fallbackHandler": fallback_handler}),
                ("CHANGED_MASTER_COPY", {"masterCopy": master_copy}),
            ],
        )

    def test_unset_guards(self):
        """
        Unset guards are sent as ``NULL_ADDRESS``.
        """
        self.before = dataclasses.replace(
            self.before,
            guard=Account.create().address,
            module_guard=Account.create().address,
        )
        self.assert_changes(
            self.build_payloads(guard=None, module_guard=None),
            [
                ("CHANGED_GUARD", {"guard": NULL_ADDRESS}),
                ("CHANGED_MODULE_GUARD", {"moduleGuard": NULL_ADDRESS}),
            ],
        )

    def test_none_and_null_address_guards_are_equal(self):
        """
        A guard stored as ``None`` is the same as ``NULL_ADDRESS``, so no change is built.
        """
        self.assertEqual(self.build_payloads(guard=None, module_guard=None), [])


class TestTakeSafeConfigSnapshot(TestCase):
    def setUp(self):
        self.safe_status = SafeLastStatusFactory()
        self.internal_tx = InternalTxFactory(
            _from=self.safe_status.address, timestamp=timezone.now()
        )

    def test_take_safe_config_snapshot(self):
        """
        The snapshot is a copy, not changed by later status updates.
        """
        snapshot = take_safe_config_snapshot(
            "addOwnerWithThreshold", self.internal_tx, self.safe_status
        )
        self.assertEqual(
            snapshot, SafeConfigSnapshot.from_safe_status(self.safe_status)
        )
        # The processor modifies the status in place after the snapshot
        self.safe_status.owners.append(Account.create().address)
        self.assertNotEqual(snapshot.owners, self.safe_status.owners)

    def test_no_safe_status(self):
        """
        No snapshot is taken without a Safe status.
        """
        self.assertIsNone(
            take_safe_config_snapshot("changeThreshold", self.internal_tx, None)
        )

    def test_not_config_function(self):
        """
        No snapshot is taken for functions that do not change the config.
        """
        for function_name in ("execTransaction", "approveHash", "setup"):
            with self.subTest(function_name=function_name):
                self.assertIsNone(
                    take_safe_config_snapshot(
                        function_name, self.internal_tx, self.safe_status
                    )
                )

    def test_old_block(self):
        """
        No snapshot is taken for blocks older than the event window.
        """
        self.internal_tx.timestamp = timezone.now() - timedelta(minutes=61)
        self.assertIsNone(
            take_safe_config_snapshot(
                "changeThreshold", self.internal_tx, self.safe_status
            )
        )

    @override_settings(DISABLE_SERVICE_EVENTS=True)
    def test_events_disabled(self):
        """
        No snapshot is taken when service events are disabled.
        """
        self.assertIsNone(
            take_safe_config_snapshot(
                "changeThreshold", self.internal_tx, self.safe_status
            )
        )
