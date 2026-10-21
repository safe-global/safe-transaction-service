# SPDX-License-Identifier: FSL-1.1-MIT
import json
from typing import Any
from unittest import mock
from unittest.mock import MagicMock

from django.conf import settings
from django.db import OperationalError
from django.test import TestCase

import requests
from eth_account import Account
from hexbytes import HexBytes
from kombu import Connection, Exchange, Producer
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.utils import fast_keccak_text
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.util.util import to_0x_hex_str

from ...events.services.queue_service import EVENTS_APP_ID, QueueService
from ...safe_messages.models import SafeMessage, SafeMessageConfirmation
from ...safe_messages.tests.factories import SafeMessageFactory
from ..cache import CacheSafeTxsView
from ..models import MultisigConfirmation, MultisigTransaction, SafeContractDelegate
from ..services import queue_service_sync_service
from ..services.queue_service_sync_service import (
    QUEUE_SERVICE_APP_ID,
    QueueServiceClient,
    QueueServiceSyncService,
)
from .factories import (
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
)

CHAIN_ID = "1"
LOGGER_NAME = queue_service_sync_service.logger.name


def build_confirmation_data(
    owner: str | None = None,
    signature_type: SafeSignatureType = SafeSignatureType.EOA,
    created: str = "2026-10-20T10:00:00Z",
) -> dict[str, Any]:
    return {
        "owner": owner or Account.create().address,
        "signature": to_0x_hex_str(b"\x01" * 65),
        "signatureType": signature_type.name,
        "created": created,
        "modified": created,
    }


def build_multisig_transaction_data(
    safe_tx_hash: str | None = None,
    safe: str | None = None,
    confirmations: list[dict[str, Any]] | None = None,
    **kwargs,
) -> dict[str, Any]:
    return {
        "safeTxHash": safe_tx_hash
        or to_0x_hex_str(fast_keccak_text(Account.create().address)),
        "chainId": CHAIN_ID,
        "safe": safe or Account.create().address,
        "nonce": "3",
        "proposer": Account.create().address,
        "proposedVia": "OWNER",
        "proposedBy": None,
        "to": Account.create().address,
        "value": "10",
        "data": "0x1234",
        "operation": 0,
        "safeTxGas": "0",
        "baseGas": "0",
        "gasPrice": "0",
        "gasToken": None,
        "refundReceiver": None,
        "failed": None,
        "notes": "a note",
        "originName": "Safe App",
        "originUrl": "https://app.safe.global",
        "txHash": None,
        "created": "2026-10-20T09:00:00Z",
        "modified": "2026-10-20T09:00:00Z",
        "confirmations": (
            [build_confirmation_data()] if confirmations is None else confirmations
        ),
    } | kwargs


def build_multisig_transaction_event(
    safe_tx_hash: str,
    safe: str,
    event_type: str = "PENDING_MULTISIG_TRANSACTION",
) -> dict[str, Any]:
    return {
        "chainId": CHAIN_ID,
        "type": event_type,
        "address": safe,
        "safeTxHash": safe_tx_hash,
    }


def build_message_data(
    message_hash: str | None = None,
    confirmations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "messageHash": message_hash
        or to_0x_hex_str(fast_keccak_text(Account.create().address)),
        "chainId": CHAIN_ID,
        "safe": Account.create().address,
        "message": "Hello Safe",
        "proposer": Account.create().address,
        "proposedVia": "OWNER",
        "proposedBy": None,
        "confirmations": (
            [build_confirmation_data()] if confirmations is None else confirmations
        ),
        "originName": "Safe App",
        "originUrl": "https://app.safe.global",
        "created": "2026-10-20T09:00:00Z",
        "modified": "2026-10-20T09:00:00Z",
    }


def build_delegate_event(
    event_type: str = "NEW_DELEGATE",
    address: str | None = None,
    chain_id: str = CHAIN_ID,
    label: str = "Delegate",
    delegate: str | None = None,
    delegator: str | None = None,
) -> dict[str, Any]:
    return {
        "chainId": chain_id,
        "type": event_type,
        "address": address,
        "delegate": delegate or Account.create().address,
        "delegator": delegator or Account.create().address,
        "label": label,
        "expiryDateSeconds": None,
    }


def build_http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Error", response=response)


class TestQueueServiceSyncService(TestCase):
    def setUp(self):
        self.queue_service_client = MagicMock(spec=QueueServiceClient)
        self.set_queue_service_delegates()
        self.connection = Connection(settings.EVENTS_QUEUE_URL)
        self.sync_service = QueueServiceSyncService(
            self.queue_service_client, self.connection, CHAIN_ID
        )
        with self.connection.channel() as channel:
            queue = self.sync_service.queue(channel)
            queue.declare()
            queue.purge()

    def tearDown(self):
        self.connection.release()

    def publish(self, payload: dict[str, Any], app_id: str = QUEUE_SERVICE_APP_ID):
        with self.connection.channel() as channel:
            Producer(channel).publish(
                json.dumps(payload),
                exchange=Exchange(
                    settings.EVENTS_QUEUE_TOPIC_EXCHANGE_NAME,
                    type="topic",
                    durable=True,
                ),
                routing_key=QueueService._build_routing_key(payload),
                content_type="application/json",
                app_id=app_id,
            )

    def sync_without_events(self) -> int:
        """
        :return: Number of events processed, after checking no event was published
        """
        with mock.patch.object(QueueService, "send_events") as send_events_mock:
            with self.captureOnCommitCallbacks(execute=True):
                processed = self.sync_service.sync(time_limit_seconds=5)
        send_events_mock.assert_not_called()
        return processed

    @mock.patch.object(queue_service_sync_service, "remove_cache_view_for_addresses")
    def test_sync_multisig_transaction(
        self, remove_cache_view_for_addresses_mock: MagicMock
    ):
        tx_data = build_multisig_transaction_data(
            confirmations=[
                build_confirmation_data(),
                build_confirmation_data(signature_type=SafeSignatureType.APPROVED_HASH),
            ]
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        event = build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
        self.publish(event)
        # Event processed more than once
        self.publish(event)
        self.assertEqual(self.sync_without_events(), 2)

        # Cache is only cleared when something is stored
        remove_cache_view_for_addresses_mock.assert_called_once_with(
            CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY,
            [tx_data["safe"]],
        )

        multisig_transaction = MultisigTransaction.objects.get()
        self.assertEqual(multisig_transaction.safe_tx_hash, tx_data["safeTxHash"])
        self.assertEqual(multisig_transaction.safe, tx_data["safe"])
        self.assertEqual(multisig_transaction.proposer, tx_data["proposer"])
        self.assertIsNone(multisig_transaction.proposed_by_delegate)
        self.assertIsNone(multisig_transaction.ethereum_tx)
        self.assertEqual(multisig_transaction.to, tx_data["to"])
        self.assertEqual(multisig_transaction.value, 10)
        self.assertEqual(bytes(multisig_transaction.data), HexBytes("0x1234"))
        self.assertEqual(multisig_transaction.nonce, 3)
        self.assertEqual(multisig_transaction.gas_token, NULL_ADDRESS)
        self.assertEqual(multisig_transaction.refund_receiver, NULL_ADDRESS)
        self.assertTrue(multisig_transaction.trusted)
        self.assertEqual(
            multisig_transaction.origin,
            {
                "url": "https://app.safe.global",
                "name": "Safe App",
                "note": "a note",
            },
        )
        self.assertEqual(
            multisig_transaction.created.isoformat(), "2026-10-20T09:00:00+00:00"
        )

        # On-chain approvals are left to the indexer
        confirmation = MultisigConfirmation.objects.get()
        self.assertEqual(confirmation.multisig_transaction_id, multisig_transaction.pk)
        self.assertEqual(confirmation.owner, tx_data["confirmations"][0]["owner"])
        self.assertEqual(confirmation.signature_type, SafeSignatureType.EOA.value)
        self.assertEqual(bytes(confirmation.signature), b"\x01" * 65)

    def test_sync_multisig_transaction_proposed_by_delegate(self):
        tx_data = build_multisig_transaction_data(
            proposedVia="DELEGATE",
            proposedBy=Account.create().address,
            confirmations=[],
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)

        multisig_transaction = MultisigTransaction.objects.get()
        self.assertEqual(multisig_transaction.proposer, tx_data["proposer"])
        self.assertEqual(
            multisig_transaction.proposed_by_delegate, tx_data["proposedBy"]
        )
        self.assertFalse(MultisigConfirmation.objects.exists())

    def test_sync_nested_multisig_transaction(self):
        # A nested transaction is published as 2 events, one per transaction
        parent_safe = Account.create().address
        child_tx_data = build_multisig_transaction_data(
            proposer=parent_safe,
            proposedVia="NESTED_OWNER",
            proposedBy=Account.create().address,
            confirmations=[],
        )
        parent_tx_data = build_multisig_transaction_data(
            safe=parent_safe, to=child_tx_data["safe"]
        )
        txs_data = {
            tx_data["safeTxHash"]: tx_data
            for tx_data in (parent_tx_data, child_tx_data)
        }
        self.queue_service_client.get_multisig_transaction.side_effect = (
            lambda safe_tx_hash: txs_data[safe_tx_hash]
        )
        for tx_data in txs_data.values():
            self.publish(
                build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
            )

        self.assertEqual(self.sync_without_events(), 2)

        parent_tx = MultisigTransaction.objects.get(safe=parent_safe)
        child_tx = MultisigTransaction.objects.get(safe=child_tx_data["safe"])
        self.assertEqual(parent_tx.to, child_tx_data["safe"])
        self.assertEqual(child_tx.proposer, parent_safe)
        self.assertIsNone(child_tx.proposed_by_delegate)
        self.assertEqual(parent_tx.confirmations.count(), 1)
        self.assertEqual(child_tx.confirmations.count(), 0)

    def test_sync_multisig_transaction_confirmation_before_transaction(self):
        tx_data = build_multisig_transaction_data()
        confirmation = MultisigConfirmationFactory(
            multisig_transaction=None,
            multisig_transaction_hash=tx_data["safeTxHash"],
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)

        confirmation.refresh_from_db()
        self.assertEqual(confirmation.multisig_transaction_id, tx_data["safeTxHash"])
        self.assertEqual(MultisigConfirmation.objects.count(), 2)

    def test_sync_existing_multisig_transaction(self):
        # Only the missing confirmations are added, the transaction is not updated
        multisig_transaction = MultisigTransactionFactory(
            ethereum_tx=None,
            nonce=7,
            trusted=False,
            origin={"url": "https://other.app"},
        )
        existing_confirmation = MultisigConfirmationFactory(
            ethereum_tx=None,
            multisig_transaction=multisig_transaction,
            multisig_transaction_hash=multisig_transaction.safe_tx_hash,
        )
        tx_data = build_multisig_transaction_data(
            safe_tx_hash=multisig_transaction.safe_tx_hash,
            safe=multisig_transaction.safe,
            confirmations=[
                # Owner not checksummed
                build_confirmation_data(owner=existing_confirmation.owner.lower()),
                build_confirmation_data(created="2099-01-01T00:00:00Z"),
            ],
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)

        multisig_transaction.refresh_from_db()
        self.assertEqual(multisig_transaction.origin, {"url": "https://other.app"})
        self.assertEqual(multisig_transaction.nonce, 7)
        self.assertTrue(multisig_transaction.trusted)
        self.assertEqual(
            multisig_transaction.modified.isoformat(), "2099-01-01T00:00:00+00:00"
        )
        self.assertEqual(multisig_transaction.confirmations.count(), 2)

        # `modified` does not move back for an older confirmation
        tx_data["confirmations"].append(
            build_confirmation_data(created="2026-01-01T00:00:00Z")
        )
        self.sync_service.sync_multisig_transaction(tx_data)
        multisig_transaction.refresh_from_db()
        self.assertEqual(
            multisig_transaction.modified.isoformat(), "2099-01-01T00:00:00+00:00"
        )
        self.assertEqual(multisig_transaction.confirmations.count(), 3)

    def test_sync_existing_untrusted_multisig_transaction(self):
        multisig_transaction = MultisigTransactionFactory(
            ethereum_tx=None, trusted=False
        )
        tx_data = build_multisig_transaction_data(
            safe_tx_hash=multisig_transaction.safe_tx_hash,
            safe=multisig_transaction.safe,
            confirmations=[],
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)
        multisig_transaction.refresh_from_db()
        self.assertTrue(multisig_transaction.trusted)

    def test_sync_multisig_transaction_without_data(self):
        tx_data = build_multisig_transaction_data(data="0x")
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)
        self.assertIsNone(MultisigTransaction.objects.get().data)

    def test_sync_multisig_transaction_of_another_chain(self):
        # Safes older than v1.3.0 build the same hash on every chain
        multisig_transaction = MultisigTransactionFactory(ethereum_tx=None)
        tx_data = build_multisig_transaction_data(
            safe_tx_hash=multisig_transaction.safe_tx_hash, chainId="100"
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(
            build_multisig_transaction_data(chainId="100")
        )
        self.assertEqual(MultisigTransaction.objects.count(), 1)

        self.sync_service.sync_deleted_multisig_transaction(tx_data)
        self.assertFalse(MultisigTransaction.objects.exists())

        self.queue_service_client.get_message.return_value = build_message_data() | {
            "chainId": "100"
        }
        self.sync_service.sync_message({"messageHash": "0x1"})
        self.assertFalse(SafeMessage.objects.exists())

    def test_sync_executed_multisig_transaction(self):
        # Executed in this service
        multisig_transaction = MultisigTransactionFactory()
        tx_data = build_multisig_transaction_data(
            safe_tx_hash=multisig_transaction.safe_tx_hash
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)
        self.assertFalse(MultisigConfirmation.objects.exists())

        # Executed in the Queue Service
        tx_data = build_multisig_transaction_data(
            txHash=to_0x_hex_str(fast_keccak_text("tx"))
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.sync_service.sync_multisig_transaction(tx_data)
        self.assertEqual(MultisigTransaction.objects.count(), 1)

    def test_sync_not_found_multisig_transaction(self):
        self.queue_service_client.get_multisig_transaction.return_value = None
        self.sync_service.sync_multisig_transaction(
            {"safeTxHash": to_0x_hex_str(fast_keccak_text("not-found"))}
        )
        self.assertFalse(MultisigTransaction.objects.exists())

    @mock.patch.object(queue_service_sync_service, "remove_cache_view_for_addresses")
    def test_sync_deleted_multisig_transaction(
        self, remove_cache_view_for_addresses_mock: MagicMock
    ):
        multisig_transaction = MultisigTransactionFactory(ethereum_tx=None)
        MultisigConfirmationFactory(
            ethereum_tx=None,
            multisig_transaction=multisig_transaction,
            multisig_transaction_hash=multisig_transaction.safe_tx_hash,
        )
        executed_multisig_transaction = MultisigTransactionFactory()
        event = build_multisig_transaction_event(
            multisig_transaction.safe_tx_hash,
            multisig_transaction.safe,
            event_type="DELETED_MULTISIG_TRANSACTION",
        )

        # Not deleted while it exists in the Queue Service
        self.queue_service_client.get_multisig_transaction.return_value = (
            build_multisig_transaction_data()
        )
        self.publish(event)
        self.assertEqual(self.sync_without_events(), 1)
        self.assertTrue(
            MultisigTransaction.objects.filter(pk=multisig_transaction.pk).exists()
        )

        self.queue_service_client.get_multisig_transaction.return_value = None
        self.publish(event)
        self.publish(event | {"safeTxHash": executed_multisig_transaction.safe_tx_hash})
        self.assertEqual(self.sync_without_events(), 2)

        remove_cache_view_for_addresses_mock.assert_called_once_with(
            CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY,
            [multisig_transaction.safe],
        )
        self.assertFalse(
            MultisigTransaction.objects.filter(pk=multisig_transaction.pk).exists()
        )
        self.assertFalse(MultisigConfirmation.objects.exists())
        # Executed transactions are never deleted
        self.assertTrue(
            MultisigTransaction.objects.filter(
                pk=executed_multisig_transaction.pk
            ).exists()
        )

    def test_sync_message(self):
        message_data = build_message_data()
        self.queue_service_client.get_message.return_value = message_data
        event = {
            "chainId": CHAIN_ID,
            "type": "MESSAGE_CREATED",
            "address": message_data["safe"],
            "messageHash": message_data["messageHash"],
        }
        self.publish(event)
        self.publish(event | {"type": "MESSAGE_CONFIRMATION"})
        self.assertEqual(self.sync_without_events(), 2)

        safe_message = SafeMessage.objects.get()
        self.assertEqual(safe_message.safe, message_data["safe"])
        self.assertEqual(safe_message.message, "Hello Safe")
        self.assertEqual(safe_message.proposed_by, message_data["proposer"])
        self.assertEqual(
            safe_message.origin,
            {"url": "https://app.safe.global", "name": "Safe App"},
        )
        confirmation = SafeMessageConfirmation.objects.get()
        self.assertEqual(confirmation.owner, message_data["confirmations"][0]["owner"])
        self.assertEqual(confirmation.signature_type, SafeSignatureType.EOA.value)

    def test_sync_existing_message(self):
        message_hash = to_0x_hex_str(fast_keccak_text("message"))
        safe_message = SafeMessageFactory(
            message_hash=message_hash, origin={"url": "https://other.app"}
        )
        message_data = build_message_data(
            message_hash=message_hash,
            confirmations=[build_confirmation_data(created="2099-01-01T00:00:00Z")],
        )
        self.queue_service_client.get_message.return_value = message_data
        self.sync_service.sync_message(message_data)

        safe_message.refresh_from_db()
        self.assertEqual(safe_message.origin, {"url": "https://other.app"})
        self.assertEqual(safe_message.modified.isoformat(), "2099-01-01T00:00:00+00:00")
        self.assertEqual(safe_message.confirmations.count(), 1)

    def set_queue_service_delegates(self, *delegate_events: dict[str, Any]):
        """
        Current delegates in the Queue Service, built from the events that
        created them
        """
        self.queue_service_client.get_delegates.side_effect = (
            lambda delegate, delegator: [
                {
                    "delegate": event["delegate"],
                    "delegator": event["delegator"],
                    "chainId": None if event["chainId"] == "0" else event["chainId"],
                    "safe": event["address"],
                    "label": event["label"],
                }
                for event in delegate_events
                if event["delegate"] == delegate and event["delegator"] == delegator
            ]
        )

    def test_sync_delegate(self):
        safe_contract = SafeContractFactory()
        event = build_delegate_event(address=safe_contract.address)
        # Delegate for every Safe and every chain
        all_safes_event = build_delegate_event(chain_id="0")
        self.set_queue_service_delegates(event, all_safes_event)
        self.publish(event)
        self.publish(all_safes_event)
        # Delegate for another chain, not bound to the queue
        self.publish(build_delegate_event(chain_id="100"))
        # Safe not indexed
        self.publish(build_delegate_event(address=Account.create().address))

        with self.assertLogs(LOGGER_NAME, level="WARNING") as logs:
            self.assertEqual(self.sync_without_events(), 3)
        self.assertIn("Queue Service sync skipped event", logs.output[0])

        delegate = SafeContractDelegate.objects.get(safe_contract=safe_contract)
        self.assertEqual(delegate.delegate, event["delegate"])
        self.assertEqual(delegate.delegator, event["delegator"])
        self.assertEqual(delegate.label, "Delegate")
        self.assertIsNone(delegate.expiry_date)
        all_safes_delegate = SafeContractDelegate.objects.get(safe_contract=None)
        self.assertEqual(all_safes_delegate.delegate, all_safes_event["delegate"])

        # Update and delete, also for every Safe
        event["label"] = all_safes_event["label"] = "Updated"
        self.publish(event | {"type": "UPDATED_DELEGATE"})
        self.publish(all_safes_event | {"type": "UPDATED_DELEGATE"})
        self.assertEqual(self.sync_without_events(), 2)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)
        self.assertEqual(
            set(SafeContractDelegate.objects.values_list("label", flat=True)),
            {"Updated"},
        )

        self.set_queue_service_delegates()
        self.publish(event | {"type": "DELETED_DELEGATE", "label": ""})
        self.publish(all_safes_event | {"type": "DELETED_DELEGATE", "label": ""})
        self.assertEqual(self.sync_without_events(), 2)
        self.assertFalse(SafeContractDelegate.objects.exists())

    def test_sync_delegate_safe_not_in_this_chain(self):
        # Delegates for every chain are expected for Safes not on this chain
        with self.assertNoLogs(LOGGER_NAME, level="WARNING"):
            self.sync_service.sync_delegate(
                build_delegate_event(chain_id="0", address=Account.create().address)
            )
        self.queue_service_client.get_delegates.assert_not_called()

    def test_sync_delegate_stale_event(self):
        # A create event processed after the delegate was deleted does not
        # create it again
        event = build_delegate_event()
        self.set_queue_service_delegates()
        self.sync_service.sync_delegate(event)
        self.assertFalse(SafeContractDelegate.objects.exists())

        # An old update does not restore an old label
        self.set_queue_service_delegates(event | {"label": "Current"})
        self.sync_service.sync_delegate(event | {"type": "UPDATED_DELEGATE"})
        self.assertEqual(SafeContractDelegate.objects.get().label, "Current")

    def test_sync_deleted_delegate_keeps_other_scopes(self):
        delegate = SafeContractDelegateFactory()
        all_safes_delegate = SafeContractDelegateFactory(
            safe_contract=None,
            delegate=delegate.delegate,
            delegator=delegate.delegator,
        )
        self.set_queue_service_delegates()
        self.sync_service.sync_delegate(
            build_delegate_event(
                event_type="DELETED_DELEGATE",
                address=delegate.safe_contract_id,
                delegate=delegate.delegate,
                delegator=delegate.delegator,
            )
        )
        self.assertEqual(
            list(SafeContractDelegate.objects.values_list("pk", flat=True)),
            [all_safes_delegate.pk],
        )

    def test_sync_deleted_delegate_still_valid_for_this_chain(self):
        # Delegates for every chain and for this chain are the same row here
        chain_event = build_delegate_event(label="This chain")
        all_chains_event = build_delegate_event(
            chain_id="0",
            delegate=chain_event["delegate"],
            delegator=chain_event["delegator"],
            label="Every chain",
        )
        self.set_queue_service_delegates(chain_event, all_chains_event)
        self.sync_service.sync_delegate(all_chains_event)
        # The delegate of this chain is used
        self.assertEqual(SafeContractDelegate.objects.get().label, "This chain")

        # Deleted for this chain, the one for every chain is kept
        self.set_queue_service_delegates(all_chains_event)
        self.sync_service.sync_delegate(
            chain_event | {"type": "DELETED_DELEGATE", "label": ""}
        )
        self.assertEqual(SafeContractDelegate.objects.get().label, "Every chain")

        # Delegates of other chains do not keep it
        self.set_queue_service_delegates(chain_event | {"chainId": "100"})
        self.sync_service.sync_delegate(
            all_chains_event | {"type": "DELETED_DELEGATE", "label": ""}
        )
        self.assertFalse(SafeContractDelegate.objects.exists())

    def test_sync_delegate_expiry_date(self):
        delegate = SafeContractDelegateFactory()
        expiry_date = delegate.expiry_date
        event = build_delegate_event(
            event_type="UPDATED_DELEGATE",
            address=delegate.safe_contract_id,
            delegate=delegate.delegate,
            delegator=delegate.delegator,
            label="Updated",
        )
        self.set_queue_service_delegates(event)
        self.sync_service.sync_delegate(event)
        delegate.refresh_from_db()
        self.assertEqual(delegate.label, "Updated")
        self.assertEqual(delegate.expiry_date, expiry_date)

        # Created again in the Queue Service, without expiry date
        self.sync_service.sync_delegate(event | {"type": "NEW_DELEGATE"})
        delegate.refresh_from_db()
        self.assertIsNone(delegate.expiry_date)

    def test_sync_delegate_empty_address(self):
        # Delegate for every Safe
        event = build_delegate_event(chain_id="0")
        self.set_queue_service_delegates(event)
        self.sync_service.sync_delegate(event | {"address": ""})
        self.assertIsNone(SafeContractDelegate.objects.get().safe_contract_id)

    def test_sync_delegate_not_checksummed_addresses(self):
        safe_contract = SafeContractFactory()
        event = build_delegate_event(address=safe_contract.address)
        self.set_queue_service_delegates(event)
        self.sync_service.sync_delegate(
            event
            | {
                "address": event["address"].lower(),
                "delegate": event["delegate"].lower(),
                "delegator": event["delegator"].lower(),
            }
        )
        self.queue_service_client.get_delegates.assert_called_once_with(
            event["delegate"], event["delegator"]
        )
        delegate = SafeContractDelegate.objects.get()
        self.assertEqual(delegate.safe_contract_id, safe_contract.address)
        self.assertEqual(delegate.delegate, event["delegate"])
        self.assertEqual(delegate.delegator, event["delegator"])

    def test_sync_ignores_events_not_from_queue_service(self):
        tx_data = build_multisig_transaction_data()
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        event = build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
        self.publish(event, app_id=EVENTS_APP_ID)
        # Another chain, not bound to the queue
        self.publish(event | {"chainId": "100"})

        self.assertEqual(self.sync_without_events(), 1)
        self.queue_service_client.get_multisig_transaction.assert_not_called()
        self.assertFalse(MultisigTransaction.objects.exists())

    def test_sync_queue_service_down(self):
        tx_data = build_multisig_transaction_data()
        self.queue_service_client.get_multisig_transaction.side_effect = (
            requests.ConnectionError("Queue Service is down")
        )
        self.publish(
            build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
        )

        # The event is kept and the run stops, as many times as needed
        self.assertEqual(self.sync_without_events(), 0)
        self.assertEqual(self.sync_without_events(), 0)
        self.assertEqual(
            self.queue_service_client.get_multisig_transaction.call_count, 2
        )

        # Once the Queue Service is back, the event is processed
        self.queue_service_client.get_multisig_transaction.side_effect = None
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.assertEqual(self.sync_without_events(), 1)
        self.assertTrue(MultisigTransaction.objects.exists())

    def test_sync_queue_service_unavailable(self):
        # Restarted, overloaded or rate limited
        for status_code in (429, 500, 503):
            with self.subTest(status_code=status_code):
                tx_data = build_multisig_transaction_data()
                self.queue_service_client.get_multisig_transaction.side_effect = (
                    build_http_error(status_code)
                )
                self.publish(
                    build_multisig_transaction_event(
                        tx_data["safeTxHash"], tx_data["safe"]
                    )
                )
                # The event is kept, also after being redelivered
                self.assertEqual(self.sync_without_events(), 0)
                self.assertEqual(self.sync_without_events(), 0)

                self.queue_service_client.get_multisig_transaction.side_effect = None
                self.queue_service_client.get_multisig_transaction.return_value = (
                    tx_data
                )
                self.assertEqual(self.sync_without_events(), 1)
                self.assertTrue(
                    MultisigTransaction.objects.filter(
                        safe_tx_hash=tx_data["safeTxHash"]
                    ).exists()
                )

    def test_sync_database_unavailable(self):
        tx_data = build_multisig_transaction_data()
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.publish(
            build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
        )
        with mock.patch.object(
            MultisigTransaction.objects,
            "bulk_create",
            side_effect=OperationalError("server closed the connection"),
        ):
            # The event is kept, also after being redelivered
            self.assertEqual(self.sync_without_events(), 0)
            self.assertEqual(self.sync_without_events(), 0)

        self.assertEqual(self.sync_without_events(), 1)
        self.assertTrue(MultisigTransaction.objects.exists())

    def test_sync_unexpected_error(self):
        tx_data = build_multisig_transaction_data()
        self.queue_service_client.get_multisig_transaction.side_effect = (
            build_http_error(400)
        )
        self.publish(
            build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
        )

        # The event is requeued and the run stops
        self.assertEqual(self.sync_without_events(), 0)

        # Requeued again, it is dropped so it does not block the queue
        with self.assertLogs(LOGGER_NAME, level="WARNING") as logs:
            self.assertEqual(self.sync_without_events(), 1)
        self.assertIn("Queue Service sync skipped event", logs.output[0])
        self.assertEqual(self.sync_without_events(), 0)

    def test_sync_invalid_event(self):
        tx_data = build_multisig_transaction_data(
            confirmations=[
                build_confirmation_data() | {"signatureType": "UNKNOWN_TYPE"}
            ]
        )
        self.queue_service_client.get_multisig_transaction.return_value = tx_data
        self.publish(
            build_multisig_transaction_event(tx_data["safeTxHash"], tx_data["safe"])
        )
        # Invalid address
        self.publish(build_delegate_event(delegate="0x1234"))
        with self.assertLogs(LOGGER_NAME, level="WARNING") as logs:
            self.assertEqual(self.sync_without_events(), 2)
        self.assertEqual(len(logs.output), 2)
        # Nothing of the events is stored
        self.assertFalse(MultisigTransaction.objects.exists())
        self.assertFalse(SafeContractDelegate.objects.exists())

    def test_sync_declares_queue_once(self):
        with mock.patch("kombu.Queue.declare") as declare_mock:
            self.sync_service.sync(time_limit_seconds=1)
            self.sync_service.sync(time_limit_seconds=1)
        declare_mock.assert_called_once_with()


class TestQueueServiceClient(TestCase):
    def test_get_multisig_transaction(self):
        client = QueueServiceClient("http://queue-service/")
        safe_tx_hash = to_0x_hex_str(fast_keccak_text("tx"))
        with mock.patch.object(client.http_session, "get") as get_mock:
            get_mock.return_value.status_code = 200
            get_mock.return_value.json.return_value = {"safeTxHash": safe_tx_hash}
            self.assertEqual(
                client.get_multisig_transaction(safe_tx_hash),
                {"safeTxHash": safe_tx_hash},
            )
            get_mock.assert_called_once_with(
                f"http://queue-service/api/v1/multisig-transactions/{safe_tx_hash}",
                timeout=5,
            )

            get_mock.return_value.status_code = 404
            self.assertIsNone(client.get_multisig_transaction(safe_tx_hash))

            get_mock.return_value.status_code = 500
            get_mock.return_value.raise_for_status.side_effect = requests.HTTPError()
            with self.assertRaises(requests.HTTPError):
                client.get_message(safe_tx_hash)

    def test_get_delegates(self):
        client = QueueServiceClient("http://queue-service")
        with mock.patch.object(client.http_session, "get") as get_mock:
            get_mock.return_value.status_code = 200
            get_mock.return_value.json.side_effect = [
                {"next": "http://queue-service/next", "results": [{"label": "1"}]},
                {"next": None, "results": [{"label": "2"}]},
            ]
            self.assertEqual(
                client.get_delegates("0x1", "0x2"), [{"label": "1"}, {"label": "2"}]
            )
            self.assertEqual(
                [call.args[0] for call in get_mock.call_args_list],
                [
                    "http://queue-service/api/v1/delegates?delegate=0x1&delegator=0x2&offset=0&limit=100",
                    "http://queue-service/api/v1/delegates?delegate=0x1&delegator=0x2&offset=1&limit=100",
                ],
            )
