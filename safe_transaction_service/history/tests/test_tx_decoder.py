import logging

from django.test import TestCase

from eth_account import Account

from gnosis.safe import SafeTx
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..indexers.tx_decoder import TxDecoder

logger = logging.getLogger(__name__)


class TestTxDecoder(SafeTestCaseMixin, TestCase):
    def test_decode_execute_transaction(self):
        owners = [Account.create() for _ in range(2)]
        owner_addresses = [owner.address for owner in owners]
        threshold = 1
        safe_creation = self.deploy_test_safe(owners=owner_addresses, threshold=threshold,
                                              initial_funding_wei=self.w3.toWei(0.1, 'ether'))
        safe_address = safe_creation.safe_address
        to = Account().create().address
        value = self.w3.toWei(0.01, 'ether')
        safe_tx_gas = 200000
        data_gas = 100000

        safe_tx = SafeTx(self.ethereum_client, safe_address, to, value, b'', 0, safe_tx_gas, data_gas, self.gas_price,
                         None, None, safe_nonce=0)

        safe_tx.sign(owners[0].privateKey)

        self.assertEqual(safe_tx.call(tx_sender_address=self.ethereum_test_account.address), 1)
        tx_hash, _ = safe_tx.execute(tx_sender_private_key=self.ethereum_test_account.privateKey)
        self.ethereum_client.get_transaction_receipt(tx_hash, timeout=60)
        self.assertEqual(self.ethereum_client.get_balance(to), value)

        tx_decoder = TxDecoder()
        function_name, arguments = tx_decoder.decode_transaction(safe_tx.tx['data'])
        self.assertEqual(function_name, 'execTransaction')
        self.assertIn('baseGas', arguments)

    def test_decode_old_execute_transaction(self):
        safe_address = Account.create().address
        to = Account().create().address
        value = self.w3.toWei(0.01, 'ether')
        safe_tx_gas = 200000
        data_gas = 100000
        safe_tx = SafeTx(self.ethereum_client, safe_address, to, value, b'', 0, safe_tx_gas, data_gas, self.gas_price,
                         None, None, safe_nonce=0, safe_version='0.0.1')

        tx_decoder = TxDecoder()
        data = safe_tx.w3_tx.buildTransaction()['data']
        function_name, arguments = tx_decoder.decode_transaction(data)
        self.assertEqual(function_name, 'execTransaction')
        # self.assertIn('dataGas', arguments)
        self.assertIn('baseGas', arguments)  # Signature of the tx is the same
