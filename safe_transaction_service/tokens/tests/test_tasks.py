import logging
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from gnosis.eth.ethereum_client import EthereumNetwork

from ...utils.redis import get_redis
from ..models import TokenList
from ..tasks import fix_pool_tokens_task, update_token_info_from_token_list_task
from .factories import TokenFactory, TokenListFactory
from .mocks import token_list_mock

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

        get_network_mock.return_value = EthereumNetwork.RINKEBY
        self.assertIsNone(fix_pool_tokens_task.delay().result)

    @mock.patch(
        "safe_transaction_service.tokens.tasks.get_ethereum_network",
        return_value=EthereumNetwork.MAINNET,
    )
    @mock.patch.object(
        TokenList, "get_tokens", autospec=True, return_value=token_list_mock["tokens"]
    )
    def test_update_token_info_from_token_list_task(
        self, get_tokens_mock: MagicMock, get_ethereum_network_mock: MagicMock
    ):
        TokenListFactory()
        # No tokens in database, so nothing is updated
        self.assertEqual(update_token_info_from_token_list_task.delay().result, 0)

        # Create random token, it won't be updated as it's not matching any token on the list
        TokenFactory()
        self.assertEqual(update_token_info_from_token_list_task.delay().result, 0)

        # Create a token in the list, it should be updated
        TokenFactory(address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
        self.assertEqual(update_token_info_from_token_list_task.delay().result, 1)

        # Create another token in the list, both should be updated
        TokenFactory(address="0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")
        self.assertEqual(update_token_info_from_token_list_task.delay().result, 2)
