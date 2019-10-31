import logging

from django.test import TestCase

from eth_account import Account
from web3 import Web3

from ..models import (InternalTx, InternalTxDecoded, MultisigConfirmation,
                      MultisigTransaction, SafeContract, SafeStatus)
from .factories import EthereumTxFactory, InternalTxFactory, SafeStatusFactory

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
