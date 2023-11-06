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
        # Run indexer once to avoid previous events from previous tests
        proxy_factory_indexer.start()
        safe_contracts_count = SafeContract.objects.count()
        ethereum_tx_sent = self.proxy_factory.deploy_proxy_contract_with_nonce(
            self.ethereum_test_account, self.safe_contract.address
        )
        safe_contract_address = ethereum_tx_sent.contract_address
        self.w3.eth.wait_for_transaction_receipt(ethereum_tx_sent.tx_hash)
        # We expect 1 event and 21 blocks 20 by reindexing and 1 from safe creation
        self.assertEqual(
            proxy_factory_indexer.start(),
            (1, 21),
        )
        # Test if only 1 Safe was created
        self.assertEqual(SafeContract.objects.count(), 1 + safe_contracts_count)
        self.assertTrue(SafeContract.objects.get(address=safe_contract_address))
