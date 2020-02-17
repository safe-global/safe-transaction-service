from unittest import mock

from django.test import TestCase

from gnosis.eth import EthereumClient

from ..indexers import InternalTxIndexerProvider
from ..models import EthereumEvent, EthereumTx
from .factories import SafeMasterCopyFactory


class TestInternalTxIndexer(TestCase):

    @mock.patch.object(EthereumClient, 'current_block_number', return_value=2000, autospec=True)
    def test_internal_tx_indexer(self, ethereum_client_current_block_number_mock):
        internal_tx_indexer = InternalTxIndexerProvider()
        print(internal_tx_indexer.ethereum_client.current_block_number)
        internal_tx_indexer.start()

        SafeMasterCopyFactory()

        internal_tx_indexer.start()
