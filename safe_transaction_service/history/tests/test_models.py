import logging
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import QuerySet
from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from web3 import Web3

from gnosis.safe.safe_signature import SafeSignatureType

from safe_transaction_service.contracts.models import ContractQuerySet
from safe_transaction_service.contracts.tests.factories import ContractFactory

from ...tokens.tests.factories import TokenFactory
from ..models import (
    ERC20Transfer,
    ERC721Transfer,
    EthereumBlock,
    EthereumBlockManager,
    EthereumTx,
    EthereumTxCallType,
    IndexingStatus,
    InternalTx,
    InternalTxDecoded,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContractDelegate,
    SafeLastStatus,
    SafeMasterCopy,
    SafeStatus,
    WebHook,
)
from .factories import (
    ERC20TransferFactory,
    ERC721TransferFactory,
    EthereumBlockFactory,
    EthereumTxFactory,
    IndexingStatusFactory,
    InternalTxDecodedFactory,
    InternalTxFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
    SafeStatusFactory,
    WebHookFactory,
)
from .mocks.mocks_ethereum_tx import type_0_tx, type_2_tx
from .mocks.mocks_internal_tx_indexer import block_result

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


class TestIndexingStatus(TestCase):
    def test_indexing_status(self):
        indexing_status = IndexingStatus.objects.get()
        self.assertEqual(str(indexing_status), "ERC20_721_EVENTS - 0")

        with self.assertRaises(IntegrityError):
            # IndexingStatus should be inserted with a migration and `indexing_type` is unique
            IndexingStatusFactory(indexing_type=0)

    def test_set_erc20_721_indexing_status(self):
        self.assertTrue(IndexingStatus.objects.set_erc20_721_indexing_status(5))
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 5
        )

        self.assertTrue(IndexingStatus.objects.set_erc20_721_indexing_status(2))
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 2
        )

        self.assertTrue(
            IndexingStatus.objects.set_erc20_721_indexing_status(
                10, from_block_number=2
            )
        )
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 10
        )

        self.assertFalse(
            IndexingStatus.objects.set_erc20_721_indexing_status(
                20, from_block_number=11
            )
        )
        self.assertEqual(
            IndexingStatus.objects.get_erc20_721_indexing_status().block_number, 10
        )


class TestMultisigTransaction(TestCase):
    def test_data_should_be_decoded(self):
        try:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            multisig_transaction = MultisigTransactionFactory(
                signatures=None, operation=0
            )
            self.assertTrue(multisig_transaction.data_should_be_decoded())

            multisig_transaction = MultisigTransactionFactory(
                signatures=None, operation=1
            )
            self.assertFalse(multisig_transaction.data_should_be_decoded())

            ContractFactory(
                address=multisig_transaction.to, trusted_for_delegate_call=True
            )
            # Cache is used, so it will still be false
            self.assertFalse(multisig_transaction.data_should_be_decoded())

            # Empty cache
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            self.assertTrue(multisig_transaction.data_should_be_decoded())
        finally:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()

    def test_multisig_transaction_owners(self):
        multisig_transaction = MultisigTransactionFactory(signatures=None)
        self.assertEqual(multisig_transaction.owners, [])

        account = Account.create()
        multisig_transaction.signatures = account.signHash(
            multisig_transaction.safe_tx_hash
        )["signature"]
        multisig_transaction.save()
        self.assertEqual(multisig_transaction.owners, [account.address])

    def test_multisend(self):
        self.assertEqual(MultisigTransaction.objects.multisend().count(), 0)
        MultisigTransactionFactory()

        MultisigTransactionFactory(to="0x998739BFdAAdde7C933B942a68053933098f9EDa")
        self.assertEqual(MultisigTransaction.objects.multisend().count(), 1)

        MultisigTransactionFactory(to="0x40A2aCCbd92BCA938b02010E17A5b8929b49130D")
        self.assertEqual(MultisigTransaction.objects.multisend().count(), 2)

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

    def test_master_copy_relevant(self):
        SafeMasterCopyFactory(l2=True)
        SafeMasterCopyFactory(l2=False)
        SafeMasterCopyFactory(l2=False)

        with self.settings(ETH_L2_NETWORK=True):
            self.assertEqual(SafeMasterCopy.objects.relevant().count(), 1)
            self.assertEqual(SafeMasterCopy.objects.relevant().get().l2, True)

        with self.settings(ETH_L2_NETWORK=False):
            self.assertEqual(SafeMasterCopy.objects.relevant().count(), 3)

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
    def test_create_from_tx_dict(self):
        for tx_mock in (type_0_tx, type_2_tx):
            with self.subTest(tx_mock=tx_mock):
                tx_dict = tx_mock["tx"]
                ethereum_tx = EthereumTx.objects.create_from_tx_dict(tx_dict)
                self.assertEqual(ethereum_tx.type, tx_dict["type"], 0)
                self.assertEqual(ethereum_tx.gas_price, tx_dict["gasPrice"])
                self.assertEqual(
                    ethereum_tx.max_fee_per_gas, tx_dict.get("maxFeePerGas")
                )
                self.assertEqual(
                    ethereum_tx.max_priority_fee_per_gas,
                    tx_dict.get("maxPriorityFeePerGas"),
                )
                self.assertIsNone(ethereum_tx.gas_used)
                self.assertIsNone(ethereum_tx.status)
                self.assertIsNone(ethereum_tx.transaction_index)

                tx_receipt = tx_mock["receipt"]
                ethereum_tx.delete()
                ethereum_tx = EthereumTx.objects.create_from_tx_dict(
                    tx_dict, tx_receipt=tx_receipt
                )
                self.assertEqual(ethereum_tx.gas_price, tx_receipt["effectiveGasPrice"])
                self.assertEqual(
                    ethereum_tx.max_fee_per_gas, tx_dict.get("maxFeePerGas")
                )
                self.assertEqual(
                    ethereum_tx.max_priority_fee_per_gas,
                    tx_dict.get("maxPriorityFeePerGas"),
                )
                self.assertEqual(ethereum_tx.gas_used, tx_receipt["gasUsed"])
                self.assertEqual(ethereum_tx.status, tx_receipt["status"])
                self.assertEqual(
                    ethereum_tx.transaction_index, tx_receipt["transactionIndex"]
                )


class TestTokenTransfer(TestCase):
    def test_transfer_to_erc721(self):
        erc20_transfer = ERC20TransferFactory()
        self.assertEqual(ERC721Transfer.objects.count(), 0)
        erc20_transfer.to_erc721_transfer().save()
        self.assertEqual(ERC721Transfer.objects.count(), 1)
        erc721_transfer = ERC721Transfer.objects.get()
        self.assertEqual(erc721_transfer.ethereum_tx_id, erc20_transfer.ethereum_tx_id)
        self.assertEqual(erc721_transfer.address, erc20_transfer.address)
        self.assertEqual(erc721_transfer.log_index, erc20_transfer.log_index)
        self.assertEqual(erc721_transfer.to, erc20_transfer.to)
        self.assertEqual(erc721_transfer.token_id, erc20_transfer.value)

    def test_transfer_to_erc20(self):
        erc721_transfer = ERC721TransferFactory()
        self.assertEqual(ERC20Transfer.objects.count(), 0)
        erc721_transfer.to_erc20_transfer().save()
        self.assertEqual(ERC20Transfer.objects.count(), 1)
        erc20_transfer = ERC721Transfer.objects.get()
        self.assertEqual(erc721_transfer.ethereum_tx_id, erc20_transfer.ethereum_tx_id)
        self.assertEqual(erc721_transfer.address, erc20_transfer.address)
        self.assertEqual(erc721_transfer.log_index, erc20_transfer.log_index)
        self.assertEqual(erc721_transfer.to, erc20_transfer.to)
        self.assertEqual(erc721_transfer.token_id, erc20_transfer.value)

    def test_erc20_events(self):
        safe_address = Account.create().address
        e1 = ERC20TransferFactory(to=safe_address)
        e2 = ERC20TransferFactory(_from=safe_address)
        ERC20TransferFactory()  # This event should not appear
        self.assertEqual(ERC20Transfer.objects.to_or_from(safe_address).count(), 2)

        self.assertSetEqual(
            ERC20Transfer.objects.tokens_used_by_address(safe_address),
            {e1.address, e2.address},
        )

    def test_erc721_events(self):
        safe_address = Account.create().address
        e1 = ERC721TransferFactory(to=safe_address)
        e2 = ERC721TransferFactory(_from=safe_address)
        ERC721TransferFactory()  # This event should not appear
        self.assertEqual(ERC721Transfer.objects.to_or_from(safe_address).count(), 2)

        self.assertSetEqual(
            ERC721Transfer.objects.tokens_used_by_address(safe_address),
            {e1.address, e2.address},
        )

    def test_incoming_tokens(self):
        address = Account.create().address
        self.assertFalse(InternalTx.objects.token_incoming_txs_for_address(address))
        ERC20TransferFactory(to=address)
        self.assertEqual(
            InternalTx.objects.token_incoming_txs_for_address(address).count(), 1
        )
        ERC721TransferFactory(to=address)
        self.assertEqual(
            InternalTx.objects.token_incoming_txs_for_address(address).count(), 2
        )
        incoming_token_0 = InternalTx.objects.token_incoming_txs_for_address(address)[
            0
        ]  # Erc721 token
        incoming_token_1 = InternalTx.objects.token_incoming_txs_for_address(address)[
            1
        ]  # Erc20 token
        self.assertIsNone(incoming_token_0["_value"])
        self.assertIsNotNone(incoming_token_0["_token_id"])
        self.assertIsNone(incoming_token_1["_token_id"])
        self.assertIsNotNone(incoming_token_1["_value"])

    def test_erc721_owned_by(self):
        random_address = Account.create().address
        self.assertEqual(
            ERC721Transfer.objects.erc721_owned_by(address=random_address), []
        )
        erc721_transfer = ERC721TransferFactory(to=random_address)
        ERC721TransferFactory(
            _from=random_address, token_id=6
        )  # Not appearing as owner it's not the receiver
        ERC721TransferFactory(
            to=Account.create().address
        )  # Not appearing as it's not the owner
        ERC20TransferFactory(to=random_address)  # Not appearing as it's not an erc721
        self.assertEqual(
            len(ERC721Transfer.objects.erc721_owned_by(address=random_address)), 1
        )
        ERC721TransferFactory(
            _from=random_address,
            address=erc721_transfer.address,
            token_id=erc721_transfer.token_id,
        )  # Send the token out
        self.assertEqual(
            len(ERC721Transfer.objects.erc721_owned_by(address=random_address)), 0
        )

        # Send the token to oneself. Should only appear once
        ERC721TransferFactory(to=random_address, token_id=6)
        ERC721TransferFactory(_from=random_address, to=random_address, token_id=6)
        self.assertEqual(
            len(ERC721Transfer.objects.erc721_owned_by(address=random_address)), 1
        )

    def test_erc721_owned_by_trusted_spam(self):
        random_address = Account.create().address
        self.assertEqual(
            ERC721Transfer.objects.erc721_owned_by(address=random_address), []
        )
        erc721_transfer = ERC721TransferFactory(to=random_address)
        erc721_transfer_2 = ERC721TransferFactory(to=random_address)
        token = TokenFactory(address=erc721_transfer.address, spam=True)
        self.assertEqual(
            len(ERC721Transfer.objects.erc721_owned_by(address=random_address)), 2
        )
        self.assertEqual(
            len(
                ERC721Transfer.objects.erc721_owned_by(
                    address=random_address, exclude_spam=True
                )
            ),
            1,
        )

        self.assertEqual(
            len(
                ERC721Transfer.objects.erc721_owned_by(
                    address=random_address, only_trusted=True
                )
            ),
            0,
        )
        token.trusted = True
        token.spam = False
        token.save(update_fields=["trusted", "spam"])
        self.assertEqual(
            len(
                ERC721Transfer.objects.erc721_owned_by(
                    address=random_address, only_trusted=True
                )
            ),
            1,
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
        ERC20TransferFactory(to=ethereum_address, value=token_value)
        ERC20TransferFactory(value=token_value)  # Create tx with a random address too
        txs = InternalTx.objects.ether_and_token_txs(ethereum_address)
        self.assertEqual(txs.count(), 3)
        ERC20TransferFactory(_from=ethereum_address, value=token_value)
        self.assertEqual(txs.count(), 4)

        for i, tx in enumerate(txs):
            if tx["token_address"]:
                self.assertEqual(tx["_value"], token_value)
            else:
                self.assertEqual(tx["_value"], ether_value)
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
        ERC20TransferFactory(to=ethereum_address, value=token_value)
        ERC20TransferFactory(value=token_value)  # Create tx with a random address too
        incoming_txs = InternalTx.objects.ether_and_token_incoming_txs(ethereum_address)
        self.assertEqual(incoming_txs.count(), 2)

        # Make internal_tx more recent than ERC20Transfer
        block = EthereumBlockFactory()
        internal_tx.block_number = block.number
        internal_tx.timestamp = block.timestamp
        internal_tx.save(update_fields=["block_number", "timestamp"])

        internal_tx.ethereum_tx.block = (
            block  # As factory has a sequence, it will always be the last
        )
        internal_tx.ethereum_tx.save(update_fields=["block"])

        incoming_tx = InternalTx.objects.ether_and_token_incoming_txs(
            ethereum_address
        ).first()
        self.assertEqual(incoming_tx["_value"], ether_value)
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
        # `trace_address` is not used for ordering anymore
        internal_tx_decoded_0 = InternalTxDecodedFactory(
            internal_tx__trace_address="0", internal_tx__ethereum_tx=ethereum_tx
        )
        internal_tx_decoded_1 = InternalTxDecodedFactory(
            internal_tx__trace_address="2", internal_tx__ethereum_tx=ethereum_tx
        )
        internal_tx_decoded_15 = InternalTxDecodedFactory(
            internal_tx__trace_address="15", internal_tx__ethereum_tx=ethereum_tx
        )

        self.assertQuerysetEqual(
            InternalTxDecoded.objects.order_by_processing_queue(),
            [internal_tx_decoded_0, internal_tx_decoded_1, internal_tx_decoded_15],
        )

        internal_tx_decoded_15.function_name = "setup"
        internal_tx_decoded_15.save()
        self.assertQuerysetEqual(
            InternalTxDecoded.objects.order_by_processing_queue(),
            [internal_tx_decoded_15, internal_tx_decoded_0, internal_tx_decoded_1],
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

    def test_out_of_order_for_safe(self):
        random_safe = Account.create().address
        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        i = InternalTxDecodedFactory(
            internal_tx___from=random_safe,
            internal_tx__block_number=10,
            processed=False,
        )
        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        i.set_processed()
        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        InternalTxDecodedFactory(
            internal_tx___from=random_safe,
            internal_tx__block_number=11,
            processed=False,
        )
        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        InternalTxDecodedFactory(
            internal_tx___from=random_safe, internal_tx__block_number=9, processed=False
        )
        self.assertTrue(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))
        i.processed = False
        i.save(update_fields=["processed"])

        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        InternalTxDecodedFactory(
            internal_tx___from=random_safe, internal_tx__block_number=8, processed=True
        )
        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        InternalTxDecodedFactory(
            internal_tx___from=random_safe, internal_tx__block_number=9, processed=True
        )
        self.assertFalse(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))

        InternalTxDecodedFactory(
            internal_tx___from=random_safe, internal_tx__block_number=10, processed=True
        )
        self.assertTrue(InternalTxDecoded.objects.out_of_order_for_safe(random_safe))


class TestLastSafeStatus(TestCase):
    def test_insert(self):
        self.assertEqual(SafeStatus.objects.count(), 0)
        self.assertEqual(SafeLastStatus.objects.count(), 0)
        SafeLastStatusFactory()
        self.assertEqual(SafeStatus.objects.count(), 1)
        self.assertEqual(SafeLastStatus.objects.count(), 1)

    def test_update_or_create_from_safe_status(self):
        safe_status = SafeStatusFactory(nonce=0)
        self.assertEqual(SafeStatus.objects.count(), 1)
        self.assertEqual(SafeLastStatus.objects.count(), 0)

        safe_last_status = SafeLastStatus.objects.update_or_create_from_safe_status(
            safe_status
        )
        self.assertEqual(SafeStatus.objects.count(), 1)
        self.assertEqual(SafeLastStatus.objects.count(), 1)

        self.assertEqual(safe_status.internal_tx, safe_last_status.internal_tx)
        self.assertEqual(safe_status.address, safe_last_status.address)
        self.assertEqual(safe_status.owners, safe_last_status.owners)
        self.assertEqual(safe_status.threshold, safe_last_status.threshold)
        self.assertEqual(safe_status.nonce, safe_last_status.nonce)
        self.assertEqual(safe_status.master_copy, safe_last_status.master_copy)
        self.assertEqual(
            safe_status.fallback_handler, safe_last_status.fallback_handler
        )
        self.assertEqual(safe_status.guard, safe_last_status.guard)
        self.assertEqual(safe_status.enabled_modules, safe_last_status.enabled_modules)

        # Update SafeLastStatus
        safe_last_status.internal_tx = InternalTxFactory()
        safe_last_status.nonce = 1
        safe_last_status.save()
        self.assertEqual(SafeStatus.objects.count(), 2)
        self.assertEqual(SafeLastStatus.objects.count(), 1)

    def test_address_for_module(self):
        module_address = Account.create().address
        address = Account.create().address
        address_2 = Account.create().address
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address), []
        )
        safe_last_status = SafeLastStatusFactory(
            address=address, nonce=0, enabled_modules=[module_address]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address), [address]
        )
        safe_last_status.delete()
        safe_last_status = SafeLastStatusFactory(address=address, nonce=1)
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address), []
        )
        safe_last_status.delete()
        safe_last_status = SafeLastStatusFactory(
            address=address, nonce=2, enabled_modules=[module_address]
        )
        safe_last_status_2 = SafeLastStatusFactory(
            address=address_2, nonce=0, enabled_modules=[module_address]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address),
            [address, address_2],
        )
        # Remove the module from one of the Safes
        new_module = Account.create().address
        safe_last_status.delete()
        safe_last_status = SafeLastStatusFactory(
            address=address, nonce=3, enabled_modules=[new_module]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address), [address_2]
        )

        # Add new module for the other Safe
        safe_last_status_2.delete()
        safe_last_status_2 = SafeLastStatusFactory(
            address=address_2, nonce=1, enabled_modules=[module_address, new_module]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address), [address_2]
        )

        # Remove the module from the other Safe
        safe_last_status_2.delete()
        SafeLastStatusFactory(address=address_2, nonce=2, enabled_modules=[new_module])
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_module(module_address), []
        )

    def test_addresses_for_owner(self):
        owner_address = Account.create().address
        address = Account.create().address
        address_2 = Account.create().address
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address), []
        )
        safe_last_status = SafeLastStatusFactory(
            address=address, nonce=0, owners=[owner_address]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address), [address]
        )
        safe_last_status.delete()
        safe_last_status = SafeLastStatusFactory(address=address, nonce=1)
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address), []
        )
        safe_last_status.delete()
        safe_last_status = SafeLastStatusFactory(
            address=address, nonce=2, owners=[owner_address]
        )
        safe_last_status_2 = SafeLastStatusFactory(
            address=address_2, nonce=0, owners=[owner_address]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address),
            [address, address_2],
        )
        # Remove the owner from one of the Safes
        new_owner = Account.create().address
        safe_last_status.delete()
        safe_last_status = SafeLastStatusFactory(
            address=address, nonce=3, owners=[new_owner]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address), [address_2]
        )

        # Add new owner for the other Safe
        safe_last_status_2.delete()
        safe_last_status_2 = SafeLastStatusFactory(
            address=address_2, nonce=1, owners=[owner_address, new_owner]
        )
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address), [address_2]
        )

        # Remove the owner from the other Safe
        safe_last_status_2.delete()
        SafeLastStatusFactory(address=address_2, nonce=2, owners=[new_owner])
        self.assertCountEqual(
            SafeLastStatus.objects.addresses_for_owner(owner_address), []
        )


class TestSafeLastStatus(TestCase):
    def test_get_or_generate(self):
        address = Account.create().address
        with self.assertRaises(SafeLastStatus.DoesNotExist):
            SafeLastStatus.objects.get_or_generate(address)

        SafeStatusFactory(address=address, nonce=0)
        SafeStatusFactory(address=address, nonce=5)
        self.assertEqual(SafeLastStatus.objects.count(), 0)
        # SafeLastStatus should be created from latest SafeStatus
        self.assertEqual(SafeLastStatus.objects.get_or_generate(address).nonce, 5)
        self.assertEqual(SafeLastStatus.objects.count(), 1)

        # SafeLastStatus was already created and will not be increased
        SafeStatusFactory(address=address, nonce=7)
        self.assertEqual(SafeLastStatus.objects.get_or_generate(address).nonce, 5)

        SafeLastStatus.objects.all().delete()
        SafeLastStatusFactory(address=address, nonce=17)
        self.assertEqual(SafeLastStatus.objects.get_or_generate(address).nonce, 17)

    def test_is_corrupted(self):
        address = Account.create().address
        SafeStatusFactory(address=address, nonce=0)
        SafeStatusFactory(address=address, nonce=2)
        safe_last_status = SafeLastStatus.objects.get_or_generate(address)
        self.assertTrue(safe_last_status.is_corrupted())

        SafeStatusFactory(address=address, nonce=1)
        self.assertFalse(safe_last_status.is_corrupted())

        SafeStatus.objects.all().delete()
        self.assertFalse(safe_last_status.is_corrupted())


class TestSafeStatus(TestCase):
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

    def test_safe_status_previous(self):
        safe_status_5 = SafeStatusFactory(nonce=5)
        safe_status_7 = SafeStatusFactory(nonce=7)
        self.assertIsNone(safe_status_5.previous())
        self.assertIsNone(safe_status_7.previous())  # Not the same address
        safe_status_5.address = safe_status_7.address
        safe_status_5.save()
        self.assertEqual(safe_status_7.previous(), safe_status_5)

        safe_status_2 = SafeStatusFactory(nonce=2, address=safe_status_5.address)
        self.assertIsNone(safe_status_2.previous())
        self.assertEqual(safe_status_5.previous(), safe_status_2)


class TestSafeContractDelegate(TestCase):
    def test_get_for_safe(self):
        random_safe = Account.create().address
        self.assertCountEqual(
            SafeContractDelegate.objects.get_for_safe(random_safe, []), []
        )

        safe_contract_delegate = SafeContractDelegateFactory()
        safe_contract_delegate_2 = SafeContractDelegateFactory(
            safe_contract=safe_contract_delegate.safe_contract
        )
        safe_contract_delegate_another_safe = SafeContractDelegateFactory()
        safe_address = safe_contract_delegate.safe_contract.address

        self.assertCountEqual(
            SafeContractDelegate.objects.get_for_safe(
                safe_address,
                [safe_contract_delegate.delegator, safe_contract_delegate_2.delegator],
            ),
            [safe_contract_delegate, safe_contract_delegate_2],
        )

        another_safe_address = safe_contract_delegate_another_safe.safe_contract.address
        # Use a Safe with an owner not matching
        self.assertCountEqual(
            SafeContractDelegate.objects.get_for_safe(
                another_safe_address, [safe_contract_delegate.delegator]
            ),
            [],
        )
        self.assertCountEqual(
            SafeContractDelegate.objects.get_for_safe(
                another_safe_address, [safe_contract_delegate_another_safe.delegator]
            ),
            [safe_contract_delegate_another_safe],
        )

        # Create delegate without Safe
        safe_contract_delegate_without_safe = SafeContractDelegateFactory(
            safe_contract=None
        )
        self.assertCountEqual(
            SafeContractDelegate.objects.get_for_safe(
                safe_address,
                [
                    safe_contract_delegate.delegator,
                    safe_contract_delegate_2.delegator,
                    safe_contract_delegate_without_safe.delegator,
                ],
            ),
            [
                safe_contract_delegate,
                safe_contract_delegate_2,
                safe_contract_delegate_without_safe,
            ],
        )
        self.assertCountEqual(
            SafeContractDelegate.objects.get_for_safe(
                another_safe_address,
                [
                    safe_contract_delegate_another_safe.delegator,
                    safe_contract_delegate_without_safe.delegator,
                ],
            ),
            [safe_contract_delegate_another_safe, safe_contract_delegate_without_safe],
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
    def test_get_or_create_from_block(self):
        mock_block = block_result[0]
        self.assertEqual(EthereumBlock.objects.count(), 0)
        db_block = EthereumBlock.objects.get_or_create_from_block(mock_block)
        db_block.set_confirmed()
        self.assertEqual(db_block.confirmed, True)
        self.assertEqual(EthereumBlock.objects.count(), 1)
        with mock.patch.object(
            EthereumBlockManager, "create_from_block"
        ) as create_from_block_mock:
            # Block already exists
            EthereumBlock.objects.get_or_create_from_block(mock_block)
            create_from_block_mock.assert_not_called()

        # Test block with different block-hash but same block number
        mock_block_2 = dict(mock_block)
        mock_block_2["hash"] = Web3.keccak(text="another-hash")
        self.assertNotEqual(mock_block["hash"], mock_block_2["hash"])
        with self.assertRaises(IntegrityError):
            EthereumBlock.objects.get_or_create_from_block(mock_block_2)
            self.assertEqual(EthereumBlock.objects.count(), 1)
            db_block.refresh_from_db()
            self.assertEqual(db_block.confirmed, False)

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

    def test_oldest_than(self):
        now = timezone.now()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)
        one_week_ago = now - timedelta(weeks=1)

        ethereum_block_0 = EthereumBlockFactory(timestamp=one_week_ago)
        ethereum_block_1 = EthereumBlockFactory(timestamp=one_day_ago)
        ethereum_block_2 = EthereumBlockFactory(timestamp=one_hour_ago)
        ethereum_block_3 = EthereumBlockFactory(timestamp=now)

        self.assertEqual(EthereumBlock.objects.oldest_than(0).first(), ethereum_block_3)
        self.assertEqual(EthereumBlock.objects.oldest_than(2).first(), ethereum_block_2)
        self.assertEqual(
            EthereumBlock.objects.oldest_than(60 * 60 + 1).first(), ethereum_block_1
        )
        self.assertEqual(
            EthereumBlock.objects.oldest_than(60 * 60 + 5).first(), ethereum_block_1
        )
        self.assertEqual(
            EthereumBlock.objects.oldest_than(60 * 60 + 5).first(), ethereum_block_1
        )
        self.assertEqual(
            EthereumBlock.objects.oldest_than(60 * 60 * 24 + 1).first(),
            ethereum_block_0,
        )
        self.assertIsNone(
            EthereumBlock.objects.oldest_than(60 * 60 * 24 * 7 + 1).first(), None
        )


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
        # Transaction must be trusted
        MultisigTransactionFactory(data=b"12")
        self.assertFalse(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses()
        )

        MultisigTransactionFactory(trusted=True, data=None)
        self.assertFalse(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses()
        )
        multisig_transaction = MultisigTransactionFactory(trusted=True, data=b"12")
        MultisigTransactionFactory(
            trusted=True, data=b"12", to=multisig_transaction.to
        )  # Check distinct
        self.assertCountEqual(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses(),
            [multisig_transaction.to],
        )
        ContractFactory(address=multisig_transaction.to)
        self.assertFalse(
            MultisigTransaction.objects.not_indexed_metadata_contract_addresses()
        )

    def test_with_confirmations_required(self):
        # This should never be picked
        SafeStatusFactory(nonce=0, threshold=4)

        multisig_transaction = MultisigTransactionFactory()
        self.assertIsNone(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required
        )

        # SafeStatus not matching the EthereumTx
        safe_status = SafeStatusFactory(
            address=multisig_transaction.safe, nonce=1, threshold=8
        )
        self.assertIsNone(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required
        )

        safe_status.internal_tx.ethereum_tx = multisig_transaction.ethereum_tx
        safe_status.internal_tx.save(update_fields=["ethereum_tx"])

        self.assertEqual(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required,
            8,
        )

        # It will not be picked, as EthereumTx is not matching
        SafeStatusFactory(nonce=2, threshold=15)
        self.assertEqual(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required,
            8,
        )

        # As EthereumTx is empty, the latest safe status will be used if available
        multisig_transaction.ethereum_tx = None
        multisig_transaction.save(update_fields=["ethereum_tx"])
        self.assertIsNone(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required
        )

        # Not matching address should not return anything
        SafeLastStatusFactory(nonce=2, threshold=16)
        self.assertIsNone(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required
        )

        SafeLastStatusFactory(address=multisig_transaction.safe, nonce=2, threshold=15)
        self.assertEqual(
            MultisigTransaction.objects.with_confirmations_required()
            .first()
            .confirmations_required,
            15,
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


class TestWebHook(TestCase):
    def test_matching_for_address(self):
        addresses = [Account.create().address for _ in range(3)]
        webhook_0 = WebHookFactory(address=addresses[0])
        webhook_1 = WebHookFactory(address=addresses[1])

        self.assertCountEqual(
            WebHook.objects.matching_for_address(addresses[0]), [webhook_0]
        )
        self.assertCountEqual(
            WebHook.objects.matching_for_address(addresses[1]), [webhook_1]
        )

        webhook_2 = WebHookFactory(address=None)
        self.assertCountEqual(
            WebHook.objects.matching_for_address(addresses[0]), [webhook_0, webhook_2]
        )
        self.assertCountEqual(
            WebHook.objects.matching_for_address(addresses[1]), [webhook_1, webhook_2]
        )
        self.assertCountEqual(
            WebHook.objects.matching_for_address(addresses[2]), [webhook_2]
        )

    def test_optional_auth(self):
        web_hook = WebHookFactory.create(authorization=None)

        web_hook.full_clean()

    def test_invalid_urls(self) -> None:
        param_list = [
            "foo://bar",
            "foo",
            "://",
        ]
        for invalid_url in param_list:
            with self.subTest(msg=f"{invalid_url} is not a valid url"):
                with self.assertRaises(ValidationError):
                    web_hook = WebHookFactory.create(url=invalid_url)
                    web_hook.full_clean()

            with self.subTest(msg=f"{invalid_url} is not a valid url"):
                with self.assertRaises(ValidationError):
                    web_hook = WebHookFactory.create(url=invalid_url)
                    web_hook.full_clean()

    def test_valid_urls(self) -> None:
        param_list = [
            "http://tx-service",
            "https://tx-service",
            "https://tx-service:8000",
            "https://safe-transaction.mainnet.gnosis.io",
            "http://mainnet-safe-transaction-web.safe.svc.cluster.local",
        ]
        for valid_url in param_list:
            with self.subTest(msg=f"Valid url {valid_url} should not throw"):
                web_hook = WebHookFactory.create(url=valid_url)
                web_hook.full_clean()

            with self.subTest(msg=f"Valid url {valid_url} should not throw"):
                web_hook = WebHookFactory.create(url=valid_url)
                web_hook.full_clean()
