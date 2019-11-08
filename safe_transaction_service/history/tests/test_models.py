import logging

from django.test import TestCase

from eth_account import Account
from web3 import Web3

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..models import (EthereumTx, InternalTx, InternalTxDecoded,
                      MultisigConfirmation, MultisigTransaction, SafeContract,
                      SafeMasterCopy, SafeStatus)
from .factories import (EthereumBlockFactory, EthereumEventFactory,
                        EthereumTxFactory, InternalTxFactory,
                        SafeStatusFactory)

logger = logging.getLogger(__name__)


class TestModels(TestCase):
    def test_bind_confirmations(self):
        safe_tx_hash = Web3.sha3(text='prueba')
        ethereum_tx = EthereumTxFactory()
        MultisigConfirmation.objects.create(
            ethereum_tx=ethereum_tx,
            multisig_transaction_hash=safe_tx_hash,
            owner=Account.create().address
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
        safe_tx_hash = Web3.sha3(text='prueba')
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
            owner=Account.create().address
        )
        self.assertEqual(multisig_tx.confirmations.count(), 1)

    def test_safe_status_store_new(self):
        safe_status = SafeStatusFactory()
        self.assertEqual(SafeStatus.objects.all().count(), 1)
        internal_tx = InternalTxFactory()
        safe_status.store_new(internal_tx)
        self.assertEqual(SafeStatus.objects.all().count(), 2)

    def test_safe_contract_receiver(self):
        ethereum_tx = EthereumTxFactory()
        safe_contract = SafeContract.objects.create(address=Account.create().address, ethereum_tx=ethereum_tx)
        self.assertEqual(safe_contract.erc20_block_number, ethereum_tx.block.number)

        # Test creation with save
        safe_contract = SafeContract(address=Account.create().address, ethereum_tx=ethereum_tx)
        self.assertEqual(safe_contract.erc20_block_number, 0)
        safe_contract.save()
        self.assertEqual(safe_contract.erc20_block_number, ethereum_tx.block.number)

        # Test batch creation (signals not working)
        safe_contracts = [
            SafeContract(address=Account.create().address, ethereum_tx=ethereum_tx),
            SafeContract(address=Account.create().address, ethereum_tx=ethereum_tx)
        ]
        SafeContract.objects.bulk_create(safe_contracts)
        for safe_contract in safe_contracts:
            self.assertNotEqual(safe_contract.erc20_block_number, ethereum_tx.block.number)
            self.assertEqual(safe_contract.erc20_block_number, 0)

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


class TestEthereumTxManager(EthereumTestCaseMixin, TestCase):
    def test_create_or_update_from_tx_hashes_existing(self):
        self.assertListEqual(EthereumTx.objects.create_or_update_from_tx_hashes([]), [])
        tx_hashes = ['0x52fcb05f2ad209d53d84b0a9a7ce6474ab415db88bc364c088758d70c8b5b0ef']
        with self.assertRaises(TypeError):
            EthereumTx.objects.create_or_update_from_tx_hashes(tx_hashes)

        # Test with database txs
        ethereum_txs = [EthereumTxFactory() for _ in range(4)]
        tx_hashes = [ethereum_tx.tx_hash for ethereum_tx in ethereum_txs]
        db_txs = EthereumTx.objects.create_or_update_from_tx_hashes(tx_hashes)
        self.assertEqual(len(db_txs), len(tx_hashes))
        for db_tx in db_txs:
            self.assertIsNotNone(db_tx)

        # Test with real txs
        value = 6
        real_tx_hashes = [self.send_ether(Account.create().address, value) for _ in range(2)]
        ethereum_txs = EthereumTx.objects.create_or_update_from_tx_hashes(real_tx_hashes)
        self.assertEqual(len(ethereum_txs), len(ethereum_txs))
        for ethereum_tx in ethereum_txs:
            self.assertEqual(ethereum_tx.value, value)

        # Remove blocks and try again
        EthereumTx.objects.filter(tx_hash__in=real_tx_hashes).update(block=None)
        ethereum_txs = EthereumTx.objects.create_or_update_from_tx_hashes(real_tx_hashes)
        for ethereum_tx in ethereum_txs:
            self.assertIsNotNone(ethereum_tx.block)

        # Test mixed
        tx_hashes = tx_hashes + real_tx_hashes
        mixed_txs = EthereumTx.objects.create_or_update_from_tx_hashes(tx_hashes)
        self.assertEqual(len(mixed_txs), len(tx_hashes))
        for mixed_tx in mixed_txs:
            self.assertIsNotNone(mixed_tx)


class TestInternalTxManager(TestCase):
    def test_incoming_txs_with_events(self):
        ethereum_address = Account.create().address
        incoming_txs = InternalTx.objects.incoming_txs_with_events(ethereum_address)
        self.assertFalse(incoming_txs)

        ether_value = 5
        internal_tx = InternalTxFactory(to=ethereum_address, value=ether_value)
        InternalTxFactory(value=ether_value)  # Create tx with a random address too
        incoming_txs = InternalTx.objects.incoming_txs_with_events(ethereum_address)
        self.assertEqual(incoming_txs.count(), 1)

        token_value = 10
        ethereum_event = EthereumEventFactory(to=ethereum_address, value=token_value)
        EthereumEventFactory(value=token_value)  # Create tx with a random address too
        incoming_txs = InternalTx.objects.incoming_txs_with_events(ethereum_address)
        self.assertEqual(incoming_txs.count(), 2)

        # Make internal_tx more recent than ethereum_event
        internal_tx.ethereum_tx.block = EthereumBlockFactory()  # As factory has a sequence, it will always be the last
        internal_tx.ethereum_tx.save()

        incoming_tx = InternalTx.objects.incoming_txs_with_events(ethereum_address).first()
        self.assertEqual(incoming_tx['value'], ether_value)
        self.assertIsNone(incoming_tx['token_address'])
