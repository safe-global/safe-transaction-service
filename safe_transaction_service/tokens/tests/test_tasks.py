import logging
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import EthereumNetwork

from ..tasks import fix_uniswap_pool_tokens_task

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    @mock.patch.object(EthereumClient, 'get_network', autospec=True, return_value=EthereumNetwork.MAINNET)
    def test_fix_uniswap_pool_tokens_task(self, get_network_mock: MagicMock):
        self.assertEqual(fix_uniswap_pool_tokens_task.delay().result, 0)

        get_network_mock.return_value = EthereumNetwork.RINKEBY
        self.assertIsNone(fix_uniswap_pool_tokens_task.delay().result)
