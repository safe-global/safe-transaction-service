from unittest import mock
from unittest.mock import PropertyMock

from django.test import TestCase

from gnosis.eth import EthereumClient

from ..indexers import InternalTxIndexerProvider
from ..models import EthereumEvent, EthereumTx
from .factories import SafeMasterCopyFactory


class TestInternalTxIndexer(TestCase):
    @mock.patch.object(EthereumClient, 'current_block_number', new_callable=PropertyMock)
    def test_internal_tx_indexer(self, current_block_number_mock):
        CURRENT_BLOCK_NUMBER = 2000
        current_block_number_mock.return_value = CURRENT_BLOCK_NUMBER

        internal_tx_indexer = InternalTxIndexerProvider()
        self.assertEqual(internal_tx_indexer.ethereum_client.current_block_number, CURRENT_BLOCK_NUMBER)

        internal_tx_indexer.start()

        SafeMasterCopyFactory()

        internal_tx_indexer.start()
