import logging
from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase
from django.utils import timezone

from eth_account import Account

from gnosis.eth.ethereum_client import (
    EthereumClient,
    EthereumClientProvider,
    EthereumNetwork,
)

from ...history.tests.utils import just_test_if_mainnet_node
from ...utils.redis import get_redis
from ..services import PriceService, PriceServiceProvider
from ..tasks import (
    EthValueWithTimestamp,
    calculate_token_eth_price_task,
    fix_pool_tokens_task,
)

logger = logging.getLogger(__name__)


class TestTasks(TestCase):
    def setUp(self) -> None:
        PriceServiceProvider.del_singleton()
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

    @mock.patch.object(
        PriceService, "get_token_eth_value", autospec=True, return_value=4815
    )
    @mock.patch.object(timezone, "now", return_value=timezone.now())
    def test_calculate_token_eth_price_task(
        self, timezone_now_mock: MagicMock, get_token_eth_value_mock: MagicMock
    ):
        random_token_address = Account.create().address
        random_redis_key = Account.create().address
        expected = EthValueWithTimestamp(
            get_token_eth_value_mock.return_value, timezone_now_mock.return_value
        )
        self.assertEqual(
            calculate_token_eth_price_task.delay(
                random_token_address, random_redis_key
            ).result,
            expected,
        )

        # Check caching works even if we change the token_address
        another_token_address = Account.create().address
        self.assertEqual(
            calculate_token_eth_price_task.delay(
                another_token_address, random_redis_key
            ).result,
            expected,
        )

        with self.settings(CELERY_ALWAYS_EAGER=False):
            random_token_address = Account.create().address
            random_redis_key = Account.create().address
            calculate_token_eth_price_task.delay(random_token_address, random_redis_key)

    def test_calculate_token_eth_price_task_without_mock(self):
        mainnet_node_url = just_test_if_mainnet_node()
        EthereumClientProvider.instance = EthereumClient(mainnet_node_url)

        dai_address = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
        random_redis_key = Account.create().address
        eth_value_with_timestamp = calculate_token_eth_price_task(
            dai_address, random_redis_key
        )
        self.assertGreater(eth_value_with_timestamp.eth_value, 0.0)

        pool_together_address = "0x334cBb5858417Aee161B53Ee0D5349cCF54514CF"
        random_redis_key = Account.create().address
        eth_value_with_timestamp = calculate_token_eth_price_task(
            pool_together_address, random_redis_key
        )
        self.assertGreater(eth_value_with_timestamp.eth_value, 0.0)

        random_token_address = Account.create().address
        random_redis_key = Account.create().address
        eth_value_with_timestamp = calculate_token_eth_price_task(
            random_token_address, random_redis_key
        )
        self.assertEqual(eth_value_with_timestamp.eth_value, 0.0)
        del EthereumClientProvider.instance

    @mock.patch.object(
        PriceService, "get_token_eth_value", autospec=True, return_value=4815
    )
    @mock.patch.object(
        PriceService, "get_token_usd_price", autospec=True, return_value=0.0
    )
    @mock.patch.object(timezone, "now", return_value=timezone.now())
    def test_return_last_valid_token_price(
        self,
        timezone_now_mock: MagicMock,
        get_token_usd_price: MagicMock,
        get_token_eth_value_mock: MagicMock,
    ):
        random_token_address = Account.create().address
        random_redis_key = Account.create().address
        expected = EthValueWithTimestamp(
            get_token_eth_value_mock.return_value, timezone_now_mock.return_value
        )
        self.assertEqual(
            calculate_token_eth_price_task.delay(
                random_token_address, random_redis_key
            ).result,
            expected,
        )

        get_token_eth_value_mock.return_value = 0.0

        self.assertEqual(
            calculate_token_eth_price_task.delay(
                random_token_address, random_redis_key, True
            ).result,
            expected,
        )
