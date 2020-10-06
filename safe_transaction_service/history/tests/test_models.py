import logging

from django.test import TestCase

from eth_account import Account
from web3 import Web3

from gnosis.safe.safe_signature import SafeSignatureType

from ..models import (EthereumEvent, EthereumTxCallType, InternalTx,
                      InternalTxDecoded, MultisigConfirmation,
                      MultisigTransaction, SafeContractDelegate,
                      SafeMasterCopy, SafeStatus)
from .factories import (EthereumBlockFactory, EthereumEventFactory,
                        EthereumTxFactory, InternalTxFactory,
                        MultisigConfirmationFactory,
                        MultisigTransactionFactory,
                        SafeContractDelegateFactory, SafeStatusFactory)

logger = logging.getLogger(__name__)


class TestModelSignals(TestCase):
    def test_bind_confirmations(self):
        safe_tx_hash = Web3.keccak(text='prueba')
        ethereum_tx = EthereumTxFactory()
        MultisigConfirmation.objects.create(
            ethereum_tx=ethereum_tx,
            multisig_transaction_hash=safe_tx_hash,
            owner=Account.create().address,
            signature_type=SafeSignatureType.EOA.value,
        )
        multisig_tx, _ = MultisigTransaction.objects.get_or_create(safe_tx_hash=safe_tx_hash,
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
                                                                   nonce=0)
        self.assertEqual(multisig_tx.confirmations.count(), 1)

    def test_bind_confirmations_reverse(self):
        safe_tx_hash = Web3.keccak(text='prueba')
        ethereum_tx = EthereumTxFactory()
        multisig_tx, _ = MultisigTransaction.objects.get_or_create(safe_tx_hash=safe_tx_hash,
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
                                                                   nonce=0)
        self.assertEqual(multisig_tx.confirmations.count(), 0)

        MultisigConfirmation.objects.create(
            ethereum_tx=ethereum_tx,
            multisig_transaction_hash=safe_tx_hash,
            owner=Account.create().address,
            signature_type=SafeSignatureType.EOA.value,
        )
        self.assertEqual(multisig_tx.confirmations.count(), 1)


class TestSafeMasterCopy(TestCase):
    def test_safe_master_copy_sorting(self):
        SafeMasterCopy.objects.create(address=Account.create().address,
                                      initial_block_number=3,
                                      tx_block_number=5)

        SafeMasterCopy.objects.create(address=Account.create().address,
                                      initial_block_number=2,
                                      tx_block_number=1)

        SafeMasterCopy.objects.create(address=Account.create().address,
                                      initial_block_number=6,
                                      tx_block_number=3)

        initial_block_numbers = [safe_master_copy.initial_block_number
                                 for safe_master_copy in SafeMasterCopy.objects.all()]

        self.assertEqual(initial_block_numbers, [2, 6, 3])


class TestEthereumTx(TestCase):
    pass


class TestEthereumEvent(TestCase):
    def test_incoming_tokens(self):
        address = Account.create().address
        self.assertFalse(InternalTx.objects.token_incoming_txs_for_address(address))
        EthereumEventFactory(to=address)
        self.assertEqual(InternalTx.objects.token_incoming_txs_for_address(address).count(), 1)
        EthereumEventFactory(to=address, erc721=True)
        self.assertEqual(InternalTx.objects.token_incoming_txs_for_address(address).count(), 2)
        incoming_token_0 = InternalTx.objects.token_incoming_txs_for_address(address)[0]  # Erc721 token
        incoming_token_1 = InternalTx.objects.token_incoming_txs_for_address(address)[1]  # Erc20 token
        self.assertIsNone(incoming_token_0.value)
        self.assertIsNotNone(incoming_token_0.token_id)
        self.assertIsNone(incoming_token_1.token_id)
        self.assertIsNotNone(incoming_token_1.value)

    def test_erc721_owned_by(self):
        random_address = Account.create().address
        self.assertEqual(EthereumEvent.objects.erc721_owned_by(address=random_address), [])
        ethereum_event = EthereumEventFactory(to=random_address, erc721=True)
        EthereumEventFactory(from_=random_address, erc721=True, value=6)  # Not appearing as owner it's not the receiver
        EthereumEventFactory(to=Account.create().address, erc721=True)  # Not appearing as it's not the owner
        EthereumEventFactory(to=random_address)  # Not appearing as it's not an erc721
        self.assertEqual(len(EthereumEvent.objects.erc721_owned_by(address=random_address)), 1)
        EthereumEventFactory(from_=random_address, erc721=True,
                             address=ethereum_event.address,
                             value=ethereum_event.arguments['tokenId'])  # Send the token out
        self.assertEqual(len(EthereumEvent.objects.erc721_owned_by(address=random_address)), 0)


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
            if tx['token_address']:
                self.assertEqual(tx['value'], token_value)
            else:
                self.assertEqual(tx['value'], ether_value)
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
        internal_tx.ethereum_tx.block = EthereumBlockFactory()  # As factory has a sequence, it will always be the last
        internal_tx.ethereum_tx.save()

        incoming_tx = InternalTx.objects.ether_and_token_incoming_txs(ethereum_address).first()
        self.assertEqual(incoming_tx['value'], ether_value)
        self.assertIsNone(incoming_tx['token_address'])

    def test_internal_tx_can_be_decoded(self):
        trace_address = '0,0,20,0'
        trace_address_parent = '0,0,20'
        internal_tx = InternalTxFactory(call_type=EthereumTxCallType.DELEGATE_CALL.value, trace_address=trace_address,
                                        error=None, data=b'123', ethereum_tx__status=1)
        self.assertFalse(internal_tx.parent_is_errored())
        self.assertTrue(internal_tx.can_be_decoded)

        parent_internal_tx = InternalTxFactory(trace_address=trace_address_parent, error='Reverted',
                                               ethereum_tx=internal_tx.ethereum_tx)
        self.assertTrue(internal_tx.parent_is_errored())
        self.assertFalse(internal_tx.can_be_decoded)

        parent_internal_tx.error = None
        parent_internal_tx.save(update_fields=['error'])
        self.assertFalse(internal_tx.parent_is_errored())
        self.assertTrue(internal_tx.can_be_decoded)

    def test_internal_txs_can_be_decoded(self):
        InternalTxFactory(call_type=EthereumTxCallType.CALL.value)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 0)

        internal_tx = InternalTxFactory(call_type=EthereumTxCallType.DELEGATE_CALL.value,
                                        error=None, data=b'123', ethereum_tx__status=1)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxFactory(call_type=EthereumTxCallType.DELEGATE_CALL.value,
                          error=None, data=None, ethereum_tx__status=1)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxFactory(call_type=EthereumTxCallType.DELEGATE_CALL.value,
                          error='aloha', data=b'123', ethereum_tx__status=1)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxFactory(call_type=EthereumTxCallType.DELEGATE_CALL.value,
                          error='aloha', data=b'123', ethereum_tx__status=0)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)

        InternalTxDecoded.objects.create(function_name='alo', arguments={}, internal_tx=internal_tx)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 0)

    def test_internal_txs_parent(self):
        # Test parent trace errored
        trace_address = '0,0,20,0'
        trace_address_parent = '0,0,20'
        another_trace = '0,1'
        internal_tx = InternalTxFactory(call_type=EthereumTxCallType.DELEGATE_CALL.value, trace_address=trace_address,
                                        error=None, data=b'123', ethereum_tx__status=1)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)
        not_a_parent_internal_tx = InternalTxFactory(trace_address=another_trace, error='Reverted',
                                                     ethereum_tx=internal_tx.ethereum_tx)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)
        parent_internal_tx = InternalTxFactory(trace_address=trace_address_parent, error='Reverted',
                                               ethereum_tx=internal_tx.ethereum_tx)
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 0)
        parent_internal_tx.error = None
        parent_internal_tx.save(update_fields=['error'])
        self.assertEqual(InternalTx.objects.can_be_decoded().count(), 1)


class TestSafeStatus(TestCase):
    def test_safe_status_store_new(self):
        safe_status = SafeStatusFactory()
        self.assertEqual(SafeStatus.objects.all().count(), 1)
        internal_tx = InternalTxFactory()
        safe_status.store_new(internal_tx)
        self.assertEqual(SafeStatus.objects.all().count(), 2)

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
        self.assertCountEqual(SafeStatus.objects.addresses_for_owner(owner_address), [])
        SafeStatusFactory(address=address, nonce=0, owners=[owner_address])
        self.assertCountEqual(SafeStatus.objects.addresses_for_owner(owner_address), [address])
        SafeStatusFactory(address=address, nonce=1)
        self.assertCountEqual(SafeStatus.objects.addresses_for_owner(owner_address), [])
        SafeStatusFactory(address=address, nonce=2, owners=[owner_address])
        SafeStatusFactory(address=address_2, nonce=0, owners=[owner_address])
        self.assertCountEqual(SafeStatus.objects.addresses_for_owner(owner_address), [address, address_2])


class TestSafeContract(TestCase):
    def test_get_delegates_for_safe(self):
        random_safe = Account.create().address
        self.assertEqual(SafeContractDelegate.objects.get_delegates_for_safe(random_safe), [])

        safe_contract_delegate = SafeContractDelegateFactory()
        safe_contract_delegate_2 = SafeContractDelegateFactory(safe_contract=safe_contract_delegate.safe_contract)
        safe_contract_delegate_another_safe = SafeContractDelegateFactory()
        safe_address = safe_contract_delegate.safe_contract.address
        self.assertCountEqual(SafeContractDelegate.objects.get_delegates_for_safe(safe_address),
                              [safe_contract_delegate.delegate, safe_contract_delegate_2.delegate])

        another_safe_address = safe_contract_delegate_another_safe.safe_contract.address
        self.assertCountEqual(SafeContractDelegate.objects.get_delegates_for_safe(another_safe_address),
                              [safe_contract_delegate_another_safe.delegate])


class TestMultisigConfirmations(TestCase):
    def test_remove_unused_confirmations(self):
        safe_address = Account.create().address
        owner_address = Account.create().address
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=0,
                                                            multisig_transaction__ethereum_tx=None,
                                                            multisig_transaction__safe=safe_address)
        self.assertEqual(MultisigConfirmation.objects.remove_unused_confirmations(safe_address, 0, owner_address), 1)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)

        # With an executed multisig transaction it shouldn't delete the confirmation
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=0,
                                                            multisig_transaction__safe=safe_address)
        self.assertEqual(MultisigConfirmation.objects.remove_unused_confirmations(safe_address, 0, owner_address), 0)
        self.assertEqual(MultisigConfirmation.objects.all().delete()[0], 1)

        # More testing
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=0,
                                                            multisig_transaction__safe=safe_address)
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=0,
                                                            multisig_transaction__ethereum_tx=None,
                                                            multisig_transaction__safe=safe_address)
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=1,
                                                            multisig_transaction__ethereum_tx=None,
                                                            multisig_transaction__safe=safe_address)
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=1,
                                                            multisig_transaction__ethereum_tx=None,
                                                            multisig_transaction__safe=safe_address)
        multisig_confirmation = MultisigConfirmationFactory(owner=owner_address,
                                                            multisig_transaction__nonce=1,
                                                            multisig_transaction__ethereum_tx=None,
                                                            multisig_transaction__safe=safe_address)
        self.assertEqual(MultisigConfirmation.objects.remove_unused_confirmations(safe_address, 1, owner_address), 3)
        self.assertEqual(MultisigConfirmation.objects.all().delete()[0], 2)


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
