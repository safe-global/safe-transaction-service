import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import QuerySet
from django.test import TestCase

from eth_account import Account
from web3 import Web3

from gnosis.safe.safe_signature import SafeSignatureType

from safe_transaction_service.contracts.tests.factories import ContractFactory

from ..models import (
    EthereumEvent,
    EthereumTxCallType,
    InternalTx,
    InternalTxDecoded,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContractDelegate,
    SafeMasterCopy,
    SafeStatus,
)
from .factories import (
    EthereumBlockFactory,
    EthereumEventFactory,
    EthereumTxFactory,
    InternalTxDecodedFactory,
    InternalTxFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
    SafeMasterCopyFactory,
    SafeStatusFactory,
)

logger = logging.getLogger(__name__)


class TestModelSignals(TestCase):
    def test_bind_confirmations(self):
        safe_tx_hash = Web3.keccak(text="prueba")
        ethereum_tx = EthereumTxFactory()
        MultisigConfirmation.objects.create(
            ethereum_tx=ethereum_tx,
            multisig_transaction_hash=safe_tx_hash,
            owner=Account.create().address,
            signature_type=SafeSignatureType.EOA.value,
        )
        multisig_tx, _ = MultisigTransaction.objects.get_or_create(
            safe_tx_hash=safe_tx_hash,
            safe=Account.create().address,
            ethereum_tx=None,
            to=Account.create().address,
            value=0,
            data=None,
            operation=0,
            safe_tx_gas=100000,
            base_gas=20000,
            gas_price=1,
            gas_token=None,
            refund_receiver=None,
            signatures=None,
            nonce=0,
        )
        self.assertEqual(multisig_tx.confirmations.count(), 1)

    def test_bind_confirmations_reverse(self):
        safe_tx_hash = Web3.keccak(text="prueba")
        ethereum_tx = EthereumTxFactory()
        multisig_tx, _ = MultisigTransaction.objects.get_or_create(
            safe_tx_hash=safe_tx_hash,
            safe=Account.create().address,
            ethereum_tx=None,
            to=Account.create().address,
            value=0,
            data=None,
            operation=0,
            safe_tx_gas=100000,
            base_gas=20000,
            gas_price=1,
            gas_token=None,
            refund_receiver=None,
            signatures=None,
            nonce=0,
        )
        self.assertEqual(multisig_tx.confirmations.count(), 0)

        MultisigConfirmation.objects.create(
            ethereum_tx=ethereum_tx,
            multisig_transaction_hash=safe_tx_hash,
            owner=Account.create().address,
            signature_type=SafeSignatureType.EOA.value,
        )
        self.assertEqual(multisig_tx.confirmations.count(), 1)


class TestModelMixins(TestCase):
    def test_bulk_create_from_generator(self):
        self.assertEqual(
            InternalTx.objects.bulk_create_from_generator(
                (x for x in range(0)), ignore_conflicts=True
            ),
            0,
        )
        number = 5
        internal_txs = (InternalTxFactory() for _ in range(number))
        self.assertEqual(
            InternalTx.objects.bulk_create_from_generator(
                internal_txs, ignore_conflicts=True
            ),
            number,
        )
        internal_txs = [InternalTxFactory() for _ in range(number)]
        InternalTx.objects.all().delete()
        another_generator = (x for x in internal_txs)
        self.assertEqual(
            InternalTx.objects.bulk_create_from_generator(
                another_generator, batch_size=2
            ),
            number,
        )


class TestMultisigTransaction(TestCase):
    def test_multisig_transaction_owners(self):
        multisig_transaction = MultisigTransactionFactory(signatures=None)
        self.assertEqual(multisig_transaction.owners, [])

        account = Account.create()
        multisig_transaction.signatures = account.signHash(
            multisig_transaction.safe_tx_hash
        )["signature"]
        multisig_transaction.save()
        self.assertEqual(multisig_transaction.owners, [account.address])

    def test_queued(self):
        safe_address = Account.create().address
        queryset = MultisigTransaction.objects.queued(safe_address)
        self.assertEqual(queryset.count(), 0)
        MultisigTransactionFactory(safe=safe_address, nonce=0, ethereum_tx=None)
        self.assertEqual(queryset.all().count(), 1)
        MultisigTransactionFactory(safe=safe_address, nonce=0)
        self.assertEqual(queryset.all().count(), 0)
        MultisigTransactionFactory(safe=safe_address, nonce=1, ethereum_tx=None)
        self.assertEqual(queryset.all().count(), 1)
        MultisigTransactionFactory(safe=safe_address, nonce=2, ethereum_tx=None)
        self.assertEqual(queryset.all().count(), 2)
        MultisigTransactionFactory(nonce=10)  # Other Safe, it must not affect
        self.assertEqual(queryset.all().count(), 2)
        MultisigTransactionFactory(safe=safe_address, nonce=10)  # Last executed tx
        self.assertEqual(queryset.all().count(), 0)
        MultisigTransactionFactory(
            safe=safe_address, nonce=7, ethereum_tx=None
        )  # Not queued (7 < 10)
        MultisigTransactionFactory(
            safe=safe_address, nonce=22, ethereum_tx=None
        )  # Queued (22 > 10)
        MultisigTransactionFactory(
            safe=safe_address, nonce=22, ethereum_tx=None
        )  # Queued (22 > 10)
        MultisigTransactionFactory(
            safe=safe_address, nonce=57, ethereum_tx=None
        )  # Queued (22 > 10)
        self.assertEqual(queryset.all().count(), 3)
        MultisigTransactionFactory(
            safe=safe_address, nonce=22
        )  # only nonce=57 will be queued
        self.assertEqual(queryset.all().count(), 1)


class TestSafeMasterCopy(TestCase):
    def test_safe_master_copy_sorting(self):
        SafeMasterCopy.objects.create(
            address=Account.create().address, initial_block_number=3, tx_block_number=5
        )

        SafeMasterCopy.objects.create(
            address=Account.create().address, initial_block_number=2, tx_block_number=1
        )

        SafeMasterCopy.objects.create(
            address=Account.create().address, initial_block_number=6, tx_block_number=3
        )

        initial_block_numbers = [
            safe_master_copy.initial_block_number
            for safe_master_copy in SafeMasterCopy.objects.all()
        ]

        self.assertEqual(initial_block_numbers, [2, 6, 3])

    def test_get_version_for_address(self):
        random_address = Account.create().address
        self.assertIsNone(
            SafeMasterCopy.objects.get_version_for_address(random_address)
        )

        safe_master_copy = SafeMasterCopyFactory(address=random_address)
        self.assertTrue(safe_master_copy.version)
        self.assertEqual(
            SafeMasterCopy.objects.get_version_for_address(random_address),
            safe_master_copy.version,
        )

    def test_validate_version(self):
        safe_master_copy = SafeMasterCopyFactory()
        safe_master_copy.version = ""
        with self.assertRaisesMessage(ValidationError, "cannot be blank"):
            safe_master_copy.full_clean()

        safe_master_copy.version = "not_a_version"
        with self.assertRaisesMessage(ValidationError, "is not a valid version"):
            safe_master_copy.full_clean()

        safe_master_copy.version = "2.0.1"
        self.assertIsNone(safe_master_copy.full_clean())


class TestEthereumTx(TestCase):
    pass


class TestEthereumEvent(TestCase):
    def test_erc20_events(self):
        safe_address = Account.create().address
        e1 = EthereumEventFactory(to=safe_address)
        e2 = EthereumEventFactory(from_=safe_address)
        EthereumEventFactory()  # This event should not appear
        erc20_events_count = EthereumEvent.objects.erc20_events_count_by_address(
            safe_address
        )
        self.assertEqual(erc20_events_count, 2)
        self.assertEqual(
            erc20_events_count,
            EthereumEvent.objects.erc20_events(address=safe_address).count(),
        )

        self.assertSetEqual(
            EthereumEvent.objects.erc20_tokens_used_by_address(safe_address),
            {e1.address, e2.address},
        )

    def test_erc721_events(self):
        safe_address = Account.create().address
        e1 = EthereumEventFactory(to=safe_address, erc721=True)
        e2 = EthereumEventFactory(from_=safe_address, erc721=True)
        EthereumEventFactory(erc721=True)  # This event should not appear
        erc721_events_count = EthereumEvent.objects.erc721_events_count_by_address(
            safe_address
        )
        self.assertEqual(erc721_events_count, 2)
        self.assertEqual(
            erc721_events_count,
            EthereumEvent.objects.erc721_events(address=safe_address).count(),
        )

        self.assertSetEqual(
            EthereumEvent.objects.erc721_tokens_used_by_address(safe_address),
            {e1.address, e2.address},
        )

    def test_incoming_tokens(self):
        address = Account.create().address
        self.assertFalse(InternalTx.objects.token_incoming_txs_for_address(address))
        EthereumEventFactory(to=address)
        self.assertEqual(
            InternalTx.objects.token_incoming_txs_for_address(address).count(), 1
        )
        EthereumEventFactory(to=address, erc721=True)
        self.assertEqual(
            InternalTx.objects.token_incoming_txs_for_address(address).count(), 2
        )
        incoming_token_0 = InternalTx.objects.token_incoming_txs_for_address(address)[
            0
        ]  # Erc721 token
        incoming_token_1 = InternalTx.objects.token_incoming_txs_for_address(address)[
            1
        ]  # Erc20 token
        self.assertIsNone(incoming_token_0.value)
        self.assertIsNotNone(incoming_token_0.token_id)
        self.assertIsNone(incoming_token_1.token_id)
        self.assertIsNotNone(incoming_token_1.value)

    def test_erc721_owned_by(self):
        random_address = Account.create().address
        self.assertEqual(
            EthereumEvent.objects.erc721_owned_by(address=random_address), []
        )
        ethereum_event = EthereumEventFactory(to=random_address, erc721=True)
        EthereumEventFactory(
            from_=random_address, erc721=True, value=6
        )  # Not appearing as owner it's not the receiver
        EthereumEventFactory(
            to=Account.create().address, erc721=True
        )  # Not appearing as it's not the owner
        EthereumEventFactory(to=random_address)  # Not appearing as it's not an erc721
        self.assertEqual(
            len(EthereumEvent.objects.erc721_owned_by(address=random_address)), 1
        )
        EthereumEventFactory(
            from_=random_address,
            erc721=True,
            address=ethereum_event.address,
            value=ethereum_event.arguments["tokenId"],
        )  # Send the token out
        self.assertEqual(
            len(EthereumEvent.objects.erc721_owned_by(address=random_address)), 0
        )


class TestInternalTx(TestCase):
    def test_ether_and_token_txs(self):
        ethereum_address = Account.create().address
        txs = InternalTx.objects.ether_and_token_txs(ethereum_address)
        self.assertFalse(txs)

        ether_value = 5
        internal_tx = InternalTxFactory(to=ethereum_address, value=ether_value)
        InternalTxFactory(value=ether_value)  # Create tx with a random address too
        txs = InternalTx.objects.ether_and_token_txs(ethereum_address)
        self.assertEqual(txs.count(), 1)
        internal_tx = InternalTxFactory(_from=ethereum_address, value=ether_value)
        self.assertEqual(txs.count(), 2)

        token_value = 10
        ethereum_event = EthereumEventFactory(to=ethereum_address, value=token_value)
        EthereumEventFactory(value=token_value)  # Create tx with a random address too
        txs = InternalTx.objects.ether_and_token_txs(ethereum_address)
        self.assertEqual(txs.count(), 3)
        EthereumEventFactory(from_=ethereum_address, value=token_value)
        self.assertEqual(txs.count(), 4)

        for i, tx in enumerate(txs):
            if tx["token_address"]:
                self.assertEqual(tx["value"], token_value)
            else:
                self.assertEqual(tx["value"], ether_value)
        self.assertEqual(i, 3)

        self.assertEqual(InternalTx.objects.ether_txs().count(), 3)
        self.assertEqual(InternalTx.objects.token_txs().count(), 3)

    def test_ether_and_token_incoming_txs(self):
        ethereum_address = Account.create().address
        incoming_txs = InternalTx.objects.ether_and_token_incoming_txs(ethereum_address)
        self.assertFalse(incoming_txs)

        ether_value = 5
        internal_tx = InternalTxFactory(to=ethereum_address, value=ether_value)
        InternalTxFactory(value=ether_value)  # Create tx with a random address too
        incoming_txs = InternalTx.objects.ether_and_token_incoming_txs(ethereum_address)
        self.assertEqual(incoming_txs.count(), 1)

        token_value = 10
        ethereum_event = EthereumEventFactory(to=ethereum_address, value=token_value)
        EthereumEventFactory(value=token_value)  # Create tx with a random address too
        incoming_txs = InternalTx.objects.ether_and_token_incoming_txs(ethereum_address)
        self.assertEqual(incoming_txs.count(), 2)

        # Make internal_tx more recent than ethereum_event
        internal_tx.ethereum_tx.block = (
            EthereumBlockFactory()
        )  # As factory has a sequence, it will always be the last
        internal_tx.ethereum_tx.save()

        incoming_tx = InternalTx.objects.ether_and_token_incoming_txs(
            ethereum_address
        ).first()
        self.assertEqual(incoming_tx["value"], ether_value)
        self.assertIsNone(incoming_tx["token_address"])

    def test_internal_tx_can_be_decoded(self):
        trace_address = "0,0,20,0"
        internal_tx = InternalTxFactory(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            trace_address=trace_address,
            error=None,
            data=b"123",
            ethereum_tx__status=1,
        )
        self.assertTrue(internal_tx.can_be_decoded)

        internal_tx.ethereum_tx.status = 0
        self.assertFalse(internal_tx.can_be_decoded)

    def test_internal_txs_can_be_decoded(self):
        InternalTxFactory(call_type=EthereumTxCallType.CALL.value)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 0)

        internal_tx = InternalTxFactory(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            error=None,
            data=b"123",
            ethereum_tx__status=1,
        )
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxFactory(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            error=None,
            data=None,
            ethereum_tx__status=1,
        )
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxFactory(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            error="aloha",
            data=b"123",
            ethereum_tx__status=1,
        )
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxFactory(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            error="aloha",
            data=b"123",
            ethereum_tx__status=0,
        )
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxDecoded.objects.create(
            function_name="alo", arguments={}, internal_tx=internal_tx
        )
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 0)

    def test_internal_txs_bulk(self):
        """
        This is the same for every bulk_insert
        """
        internal_txs = [InternalTxFactory() for _ in range(5)]
        for internal_tx in internal_txs:
            internal_tx.pk = None

        # If bulk inserted with `ignore_conflicts` pk will not be populated
        InternalTx.objects.all().delete()
        InternalTx.objects.bulk_create(internal_txs, ignore_conflicts=True)
        for internal_tx in internal_txs:
            self.assertIsNone(internal_tx.pk)
        InternalTx.objects.all().delete()
        InternalTx.objects.bulk_create(internal_txs[:3])
        with self.assertRaises(IntegrityError):
            InternalTx.objects.bulk_create(
                internal_txs
            )  # Cannot bulk create again first 2 transactions

    def test_get_parent_child(self):
        i = InternalTxFactory(trace_address="0")
        self.assertIsNone(i.get_parent())
        i_2 = InternalTxFactory(trace_address="0,0")
        self.assertIsNone(
            i_2.get_parent()
        )  # They must belong to the same ethereum transaction
        self.assertIsNone(
            i.get_child(0)
        )  # They must belong to the same ethereum transaction
        i_2.ethereum_tx = i.ethereum_tx
        i_2.save()

        self.assertEqual(i_2.get_parent(), i)
        self.assertEqual(i.get_child(0), i_2)
        self.assertIsNone(i.get_child(1))
        self.assertIsNone(i_2.get_child(0))


class TestInternalTxDecoded(TestCase):
    def test_order_by_processing_queue(self):
        self.assertQuerysetEqual(
            InternalTxDecoded.objects.order_by_processing_queue(), []
        )
        ethereum_tx = EthereumTxFactory()
        internal_tx_decoded_1 = InternalTxDecodedFactory(
            internal_tx__trace_address="1", internal_tx__ethereum_tx=ethereum_tx
        )
        internal_tx_decoded_0 = InternalTxDecodedFactory(
            internal_tx__trace_address="0", internal_tx__ethereum_tx=ethereum_tx
        )
        internal_tx_decoded_5 = InternalTxDecodedFactory(
            internal_tx__trace_address="5", internal_tx__ethereum_tx=ethereum_tx
        )

        self.assertQuerysetEqual(
            InternalTxDecoded.objects.order_by_processing_queue(),
            [internal_tx_decoded_0, internal_tx_decoded_1, internal_tx_decoded_5],
        )

        internal_tx_decoded_5.function_name = "setup"
        internal_tx_decoded_5.save()
        self.assertQuerysetEqual(
            InternalTxDecoded.objects.order_by_processing_queue(),
            [internal_tx_decoded_5, internal_tx_decoded_0, internal_tx_decoded_1],
        )

    def test_safes_pending_to_be_processed(self):
        self.assertCountEqual(
            InternalTxDecoded.objects.safes_pending_to_be_processed(), []
        )

        safe_address_1 = SafeContractFactory().address
        internal_tx_decoded_1 = InternalTxDecodedFactory(
            internal_tx___from=safe_address_1
        )
        InternalTxDecodedFactory(internal_tx___from=safe_address_1)
        results = InternalTxDecoded.objects.safes_pending_to_be_processed()
        self.assertIsInstance(results, QuerySet)
        self.assertCountEqual(results, [safe_address_1])

        safe_address_2 = SafeContractFactory().address
        internal_tx_decoded_2 = InternalTxDecodedFactory(
            internal_tx___from=safe_address_2
        )
        self.assertCountEqual(
            InternalTxDecoded.objects.safes_pending_to_be_processed(),
            [safe_address_1, safe_address_2],
        )

        # Safes with all processed internal txs decoded are not returned
        internal_tx_decoded_1.set_processed()
        internal_tx_decoded_2.set_processed()
        self.assertCountEqual(
            InternalTxDecoded.objects.safes_pending_to_be_processed(), [safe_address_1]
        )


class TestSafeStatus(TestCase):
    def test_safe_status_store_new(self):
        safe_status = SafeStatusFactory()
        self.assertEqual(SafeStatus.objects.all().count(), 1)
        internal_tx = InternalTxFactory()
        safe_status.store_new(internal_tx)
        self.assertEqual(SafeStatus.objects.all().count(), 2)

    def test_safe_status_is_corrupted(self):
        address = Account.create().address
        safe_status = SafeStatusFactory(nonce=0, address=address)
        self.assertFalse(safe_status.is_corrupted())
        safe_status_2 = SafeStatusFactory(nonce=1, address=address)
        self.assertFalse(safe_status_2.is_corrupted())
        safe_status_3 = SafeStatusFactory(nonce=2, address=address)
        self.assertEqual(SafeStatus.objects.count(), 3)
        safe_status_2.delete()
        self.assertEqual(SafeStatus.objects.count(), 2)
        # First SafeStatus is ok, as it has no previous SafeStatus missing
        self.assertFalse(safe_status.is_corrupted())
        self.assertTrue(safe_status_3.is_corrupted())

        SafeStatus.objects.all().delete()
        SafeStatusFactory(nonce=0, address=address)
        SafeStatusFactory(nonce=1, address=address)
        SafeStatusFactory(nonce=1, address=address)
        another_safe_status = SafeStatusFactory(nonce=2, address=address)
        self.assertFalse(another_safe_status.is_corrupted())

    def test_safe_status_last_for_address(self):
        address = Account.create().address
        SafeStatusFactory(address=address, nonce=1)
        SafeStatusFactory(address=address, nonce=0)
        SafeStatusFactory(address=address, nonce=2)
        self.assertEqual(SafeStatus.objects.last_for_address(address).nonce, 2)
        self.assertIsNone(SafeStatus.objects.last_for_address(Account.create().address))

    def test_safe_status_addresses_for_owner(self):
        owner_address = Account.create().address
        address = Account.create().address
        address_2 = Account.create().address
        self.assertEqual(SafeStatus.objects.addresses_for_owner(owner_address), set())
        SafeStatusFactory(address=address, nonce=0, owners=[owner_address])
        self.assertEqual(
            SafeStatus.objects.addresses_for_owner(owner_address), {address}
        )
        SafeStatusFactory(address=address, nonce=1)
        self.assertEqual(SafeStatus.objects.addresses_for_owner(owner_address), set())
        SafeStatusFactory(address=address, nonce=2, owners=[owner_address])
        SafeStatusFactory(address=address_2, nonce=0, owners=[owner_address])
        self.assertEqual(
            SafeStatus.objects.addresses_for_owner(owner_address), {address, address_2}
        )
        # Remove the owner from one of the Safes
        new_owner = Account.create().address
        SafeStatusFactory(address=address, nonce=3, owners=[new_owner])
        self.assertEqual(
            SafeStatus.objects.addresses_for_owner(owner_address), {address_2}
        )

        # Add new owner for the other Safe
        SafeStatusFactory(address=address_2, nonce=1, owners=[owner_address, new_owner])
        self.assertEqual(
            SafeStatus.objects.addresses_for_owner(owner_address), {address_2}
        )

        # Remove the owner from the other Safe
        SafeStatusFactory(address=address_2, nonce=2, owners=[new_owner])
        self.assertEqual(SafeStatus.objects.addresses_for_owner(owner_address), set())


class TestSafeContract(TestCase):
    def test_get_delegates_for_safe(self):
        random_safe = Account.create().address
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe(random_safe), set()
        )

        safe_contract_delegate = SafeContractDelegateFactory()
        safe_contract_delegate_2 = SafeContractDelegateFactory(
            safe_contract=safe_contract_delegate.safe_contract
        )
        safe_contract_delegate_another_safe = SafeContractDelegateFactory()
        safe_address = safe_contract_delegate.safe_contract.address
        self.assertCountEqual(
            SafeContractDelegate.objects.get_delegates_for_safe(safe_address),
            [safe_contract_delegate.delegate, safe_contract_delegate_2.delegate],
        )

        another_safe_address = safe_contract_delegate_another_safe.safe_contract.address
        self.assertCountEqual(
            SafeContractDelegate.objects.get_delegates_for_safe(another_safe_address),
            [safe_contract_delegate_another_safe.delegate],
        )

    def test_get_delegates_for_safe_and_owners(self):
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                Account.create().address, []
            ),
            set(),
        )

        owner = Account.create().address
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                Account.create().address, [owner]
            ),
            set(),
        )

        safe_contract_delegate = SafeContractDelegateFactory(
            delegator=owner, safe_contract=None
        )
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                Account.create().address, [owner]
            ),
            {safe_contract_delegate.delegate},
        )

        owner_2 = Account.create().address
        safe_contract_delegate_2 = SafeContractDelegateFactory(delegator=owner_2)
        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                safe_contract_delegate_2.safe_contract_id, [owner_2]
            ),
            {safe_contract_delegate_2.delegate},
        )

        self.assertEqual(
            SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                Account.create().address, [owner_2]
            ),
            set(),
        )


class TestMultisigConfirmations(TestCase):
    def test_remove_unused_confirmations(self):
        safe_address = Account.create().address
        owner_address = Account.create().address
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=0,
            multisig_transaction__ethereum_tx=None,
            multisig_transaction__safe=safe_address,
        )
        self.assertEqual(
            MultisigConfirmation.objects.remove_unused_confirmations(
                safe_address, 0, owner_address
            ),
            1,
        )
        self.assertEqual(MultisigConfirmation.objects.count(), 0)

        # With an executed multisig transaction it shouldn't delete the confirmation
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=0,
            multisig_transaction__safe=safe_address,
        )
        self.assertEqual(
            MultisigConfirmation.objects.remove_unused_confirmations(
                safe_address, 0, owner_address
            ),
            0,
        )
        self.assertEqual(MultisigConfirmation.objects.all().delete()[0], 1)

        # More testing
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=0,
            multisig_transaction__safe=safe_address,
        )
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=0,
            multisig_transaction__ethereum_tx=None,
            multisig_transaction__safe=safe_address,
        )
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=1,
            multisig_transaction__ethereum_tx=None,
            multisig_transaction__safe=safe_address,
        )
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=1,
            multisig_transaction__ethereum_tx=None,
            multisig_transaction__safe=safe_address,
        )
        multisig_confirmation = MultisigConfirmationFactory(
            owner=owner_address,
            multisig_transaction__nonce=1,
            multisig_transaction__ethereum_tx=None,
            multisig_transaction__safe=safe_address,
        )
        self.assertEqual(
            MultisigConfirmation.objects.remove_unused_confirmations(
                safe_address, 1, owner_address
            ),
            3,
        )
        self.assertEqual(MultisigConfirmation.objects.all().delete()[0], 2)


class TestEthereumBlock(TestCase):
    def test_set_confirmed_not_confirmed(self):
        ethereum_block = EthereumBlockFactory(confirmed=False)
        ethereum_block.set_confirmed()
        ethereum_block.refresh_from_db()
        self.assertTrue(ethereum_block.confirmed)
        # Check idempotent
        ethereum_block.set_confirmed()
        ethereum_block.refresh_from_db()
        self.assertTrue(ethereum_block.confirmed)

        ethereum_block.set_not_confirmed()
        ethereum_block.refresh_from_db()
        self.assertFalse(ethereum_block.confirmed)


class TestMultisigTransactions(TestCase):
    def test_last_nonce(self):
        safe_address = Account.create().address
        self.assertIsNone(MultisigTransaction.objects.last_nonce(safe_address))
        MultisigTransactionFactory(safe=safe_address, nonce=0)
        self.assertEqual(MultisigTransaction.objects.last_nonce(safe_address), 0)

        MultisigTransactionFactory(safe=safe_address, nonce=25)
        self.assertEqual(MultisigTransaction.objects.last_nonce(safe_address), 25)

        MultisigTransactionFactory(safe=safe_address, nonce=13)
        self.assertEqual(MultisigTransaction.objects.last_nonce(safe_address), 25)

    def test_safes_with_number_of_transactions_executed(self):
        self.assertEqual(
            MultisigTransaction.objects.safes_with_number_of_transactions_executed().count(),
            0,
        )
        safe_address_1 = Account.create().address
        safe_address_2 = Account.create().address
        safe_address_3 = Account.create().address
        MultisigTransactionFactory(safe=safe_address_1)
        MultisigTransactionFactory(safe=safe_address_1)
        safes_with_number_of_transactions = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed()
        )
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed()
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], {"safe": safe_address_1, "transactions": 2})
        MultisigTransactionFactory(safe=safe_address_1)
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed()
        )
        self.assertEqual(result[0], {"safe": safe_address_1, "transactions": 3})
        MultisigTransactionFactory(safe=safe_address_2)
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed()
        )
        self.assertEqual(
            list(result),
            [
                {"safe": safe_address_1, "transactions": 3},
                {"safe": safe_address_2, "transactions": 1},
            ],
        )
        [MultisigTransactionFactory(safe=safe_address_3) for _ in range(4)]
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed()
        )
        self.assertEqual(
            list(result),
            [
                {"safe": safe_address_3, "transactions": 4},
                {"safe": safe_address_1, "transactions": 3},
                {"safe": safe_address_2, "transactions": 1},
            ],
        )

    def test_safes_with_number_of_transactions_executed_and_master_copy(self):
        self.assertEqual(
            MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy().count(),
            0,
        )
        safe_address_1 = Account.create().address
        safe_address_2 = Account.create().address
        safe_address_3 = Account.create().address
        MultisigTransactionFactory(safe=safe_address_1)
        MultisigTransactionFactory(safe=safe_address_1)
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0], {"safe": safe_address_1, "transactions": 2, "master_copy": None}
        )
        MultisigTransactionFactory(safe=safe_address_2)
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
        )
        self.assertEqual(
            list(result),
            [
                {"safe": safe_address_1, "transactions": 2, "master_copy": None},
                {"safe": safe_address_2, "transactions": 1, "master_copy": None},
            ],
        )

        safe_status_1 = SafeStatusFactory(address=safe_address_1)
        self.assertIsNotNone(safe_status_1.master_copy)
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
        )
        self.assertEqual(
            list(result),
            [
                {
                    "safe": safe_address_1,
                    "transactions": 2,
                    "master_copy": safe_status_1.master_copy,
                },
                {"safe": safe_address_2, "transactions": 1, "master_copy": None},
            ],
        )

        safe_status_2 = SafeStatusFactory(address=safe_address_2)
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
        )
        self.assertEqual(
            list(result),
            [
                {
                    "safe": safe_address_1,
                    "transactions": 2,
                    "master_copy": safe_status_1.master_copy,
                },
                {
                    "safe": safe_address_2,
                    "transactions": 1,
                    "master_copy": safe_status_2.master_copy,
                },
            ],
        )

        [MultisigTransactionFactory(safe=safe_address_3) for _ in range(4)]
        result = (
            MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
        )
        self.assertEqual(
            list(result),
            [
                {"safe": safe_address_3, "transactions": 4, "master_copy": None},
                {
                    "safe": safe_address_1,
                    "transactions": 2,
                    "master_copy": safe_status_1.master_copy,
                },
                {
                    "safe": safe_address_2,
                    "transactions": 1,
                    "master_copy": safe_status_2.master_copy,
                },
            ],
        )

    def test_not_indexed_metadata_contract_addresses(self):
        self.assertFalse(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses()
        )

        MultisigTransactionFactory(data=None)
        self.assertFalse(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses()
        )
        multisig_transaction = MultisigTransactionFactory(data=b"12")
        MultisigTransactionFactory(
            data=b"12", to=multisig_transaction.to
        )  # Check distinct
        self.assertCountEqual(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses(),
            [multisig_transaction.to],
        )
        ContractFactory(address=multisig_transaction.to)
        self.assertFalse(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses()
        )

    def test_with_confirmations(self):
        multisig_transaction = MultisigTransactionFactory()
        self.assertEqual(MultisigTransaction.objects.with_confirmations().count(), 0)
        MultisigConfirmationFactory(multisig_transaction=multisig_transaction)
        self.assertEqual(MultisigTransaction.objects.with_confirmations().count(), 1)
        self.assertEqual(MultisigTransaction.objects.count(), 1)

    def test_without_confirmations(self):
        multisig_transaction = MultisigTransactionFactory()
        self.assertEqual(MultisigTransaction.objects.without_confirmations().count(), 1)
        MultisigConfirmationFactory(multisig_transaction=multisig_transaction)
        self.assertEqual(MultisigTransaction.objects.without_confirmations().count(), 0)
        self.assertEqual(MultisigTransaction.objects.count(), 1)

    def test_last_valid_transaction(self):
        safe_address = Account.create().address
        self.assertIsNone(
            MultisigTransaction.objects.last_valid_transaction(safe_address)
        )
        multisig_transaction = MultisigTransactionFactory(safe=safe_address, nonce=0)
        self.assertIsNone(
            MultisigTransaction.objects.last_valid_transaction(safe_address)
        )
        multisig_confirmation = MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction,
            signature_type=SafeSignatureType.EOA.value,
        )
        self.assertIsNone(
            MultisigTransaction.objects.last_valid_transaction(safe_address)
        )
        SafeStatusFactory(address=safe_address, owners=[multisig_confirmation.owner])
        self.assertEqual(
            MultisigTransaction.objects.last_valid_transaction(safe_address),
            multisig_transaction,
        )

        multisig_transaction_2 = MultisigTransactionFactory(safe=safe_address, nonce=2)
        multisig_confirmation_2 = MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction_2,
            signature_type=SafeSignatureType.EOA.value,
            owner=multisig_confirmation.owner,
        )
        self.assertEqual(
            MultisigTransaction.objects.last_valid_transaction(safe_address),
            multisig_transaction_2,
        )
