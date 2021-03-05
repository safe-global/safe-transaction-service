import logging
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import EthereumNetwork

from ..services import PriceService
from ..tasks import calculate_token_eth_price, fix_pool_tokens_task

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    @mock.patch.object(EthereumClient, 'get_network', autospec=True, return_value=EthereumNetwork.MAINNET)
    def test_fix_pool_tokens_task(self, get_network_mock: MagicMock):
        self.assertEqual(fix_pool_tokens_task.delay().result, 0)

        get_network_mock.return_value = EthereumNetwork.RINKEBY
        self.assertIsNone(fix_pool_tokens_task.delay().result)

    @mock.patch.object(PriceService, 'get_token_eth_value', autospec=True, return_value=4815)
    def test_calculate_token_eth_price(self, get_token_eth_value_mock: MagicMock):
        random_token = Account.create().address
        self.assertEqual(calculate_token_eth_price.delay('key', random_token).result,
                         get_token_eth_value_mock.return_value)

        with self.settings(CELERY_ALWAYS_EAGER=False):
            calculate_token_eth_price.delay('key', random_token)
