import logging
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from safe_eth.eth.ethereum_client import EthereumNetwork

from ...utils.redis import get_redis
from ..tasks import fix_pool_tokens_task

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    def setUp(self) -> None:
        get_redis().flushall()

    def tearDown(self) -> None:
        get_redis().flushall()

    @mock.patch(
        "safe_transaction_service.tokens.tasks.get_ethereum_network",
        return_value=EthereumNetwork.MAINNET,
    )
    def test_fix_pool_tokens_task(self, get_network_mock: MagicMock):
        self.assertEqual(fix_pool_tokens_task.delay().result, 0)

        get_network_mock.return_value = EthereumNetwork.SEPOLIA
        self.assertIsNone(fix_pool_tokens_task.delay().result)
