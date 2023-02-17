from django.test import TestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..indexers import ProxyFactoryIndexerProvider
from ..models import SafeContract
from .factories import ProxyFactoryFactory


class TestProxyFactoryIndexer(SafeTestCaseMixin, TestCase):
    def test_proxy_factory_indexer(self):
        proxy_factory_indexer = ProxyFactoryIndexerProvider()
        proxy_factory_indexer.confirmations = 0
        self.assertEqual(proxy_factory_indexer.start(), (0, 0))
        ProxyFactoryFactory(address=self.proxy_factory.address)
        ethereum_tx_sent = self.proxy_factory.deploy_proxy_contract(
            self.ethereum_test_account, self.safe_contract_address
        )
        safe_contract_address = ethereum_tx_sent.contract_address
        self.w3.eth.wait_for_transaction_receipt(ethereum_tx_sent.tx_hash)
        if (
            self.ethereum_client.current_block_number
            - proxy_factory_indexer.block_process_limit
            < 0
        ):
            # From 0 to current block
            blocks_processed = self.ethereum_client.current_block_number + 1
        else:
            # From 1 to current block
            blocks_processed = self.ethereum_client.current_block_number
        self.assertEqual(proxy_factory_indexer.start(), (1, blocks_processed))
        self.assertEqual(SafeContract.objects.count(), 1)
        self.assertTrue(SafeContract.objects.get(address=safe_contract_address))
