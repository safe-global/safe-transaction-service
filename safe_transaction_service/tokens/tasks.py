import operator
from functools import cached_property
from typing import Optional, Tuple

from django.conf import settings

from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from celery import app
from celery.utils.log import get_task_logger
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork
from gnosis.eth.oracles import (BalancerOracle, CannotGetPriceFromOracle,
                                CurveOracle, KyberOracle, MooniswapOracle,
                                OracleException, SushiswapOracle,
                                UniswapOracle, UniswapV2Oracle)
from gnosis.eth.oracles.oracles import PriceOracle, PricePoolOracle

from safe_transaction_service.history.utils import (close_gevent_db_connection,
                                                    get_redis)

from .clients import (BinanceClient, CannotGetPrice, CoingeckoClient,
                      KrakenClient, KucoinClient)
from .models import Token

logger = get_task_logger(__name__)


class BalanceAlternativeService:
    def __init__(self, ethereum_client: EthereumClient, redis: Redis,
                 uniswap_factory_address: str, kyber_network_proxy_address: str):
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.binance_client = BinanceClient()
        self.coingecko_client = CoingeckoClient()
        self.kraken_client = KrakenClient()
        self.kucoin_client = KucoinClient()
        self.curve_oracle = CurveOracle(self.ethereum_client)  # Curve returns price in usd
        self.kyber_oracle = KyberOracle(self.ethereum_client, kyber_network_proxy_address)
        self.sushiswap_oracle = SushiswapOracle(self.ethereum_client)
        self.uniswap_oracle = UniswapOracle(self.ethereum_client, uniswap_factory_address)
        self.uniswap_v2_oracle = UniswapV2Oracle(self.ethereum_client)
        self.balancer_oracle = BalancerOracle(self.ethereum_client, self.uniswap_v2_oracle)
        self.mooniswap_oracle = MooniswapOracle(self.ethereum_client, self.uniswap_v2_oracle)
        self.cache_eth_price = TTLCache(maxsize=2048, ttl=60 * 30)  # 30 minutes of caching
        self.cache_token_eth_value = TTLCache(maxsize=2048, ttl=60 * 30)  # 30 minutes of caching
        self.cache_token_usd_value = TTLCache(maxsize=2048, ttl=60 * 30)  # 30 minutes of caching
        self.cache_token_info = {}

    @cached_property
    def enabled_price_oracles(self) -> Tuple[PriceOracle]:
        if self.ethereum_network == EthereumNetwork.MAINNET:
            return self.kyber_oracle, self.uniswap_v2_oracle, self.sushiswap_oracle, self.uniswap_oracle
        else:
            return self.kyber_oracle, self.uniswap_v2_oracle  # They provide versions in another networks

    @cached_property
    def enabled_pool_price_oracles(self) -> Tuple[PricePoolOracle]:
        if self.ethereum_network == EthereumNetwork.MAINNET:
            return self.uniswap_v2_oracle, self.balancer_oracle, self.mooniswap_oracle
        else:
            return tuple()

    @cached_property
    def ethereum_network(self):
        return self.ethereum_client.get_network()

    @cachedmethod(cache=operator.attrgetter('cache_eth_price'))
    @cache_memoize(60 * 30, prefix='balances-get_eth_price')  # 30 minutes
    def get_eth_price(self) -> float:
        """
        Get USD price for Ether. It depends on the ethereum network:
            - On mainnet, use ETH/USD
            - On xDAI, use DAI/USD.
            - On EWT/VOLTA, use EWT/USD
        :return: USD price for Ether
        """
        if self.ethereum_network == EthereumNetwork.XDAI:
            try:
                return self.kraken_client.get_dai_usd_price()
            except CannotGetPrice:
                return 1  # DAI/USD should be close to 1
        elif self.ethereum_network in (EthereumNetwork.ENERGY_WEB_CHAIN, EthereumNetwork.VOLTA):
            return self.get_ewt_usd_price()
        else:
            try:
                return self.kraken_client.get_eth_usd_price()
            except CannotGetPrice:
                return self.binance_client.get_eth_usd_price()

    def get_cached_token_eth_value(self, token_address: str) -> float:
        cache_key = f'balance-service:{token_address}:eth-price'
        if eth_value := self.redis.get(cache_key):
            return float(eth_value)
        else:
            calculate_token_eth_price.delay(cache_key)

    @cachedmethod(cache=operator.attrgetter('cache_token_eth_value'))
    @cache_memoize(60 * 30, prefix='balances-get_token_eth_value')  # 30 minutes
    def get_token_eth_value(self, token_address: str) -> float:
        """
        Return current ether value for a given `token_address`
        """
        for oracle in self.enabled_price_oracles:
            try:
                return oracle.get_price(token_address)
            except OracleException:
                logger.info('Cannot get eth value for token-address=%s from %s', token_address,
                            oracle.__class__.__name__)

        # Try pool tokens
        for oracle in self.enabled_pool_price_oracles:
            try:
                return oracle.get_pool_token_price(token_address)
            except OracleException:
                logger.info('Cannot get eth value for token-address=%s from %s', token_address,
                            oracle.__class__.__name__)

        logger.warning('Cannot find eth value for token-address=%s', token_address)
        return 0.

    @cachedmethod(cache=operator.attrgetter('cache_token_usd_value'))
    @cache_memoize(60 * 30, prefix='balances-get_token_usd_price')  # 30 minutes
    def get_token_usd_price(self, token_address: str) -> float:
        """
        Return current usd value for a given `token_address` using Curve, if not use Coingecko as last resource
        """
        if self.ethereum_network == EthereumNetwork.MAINNET:
            try:
                return self.curve_oracle.get_pool_token_price(token_address)
            except CannotGetPriceFromOracle:
                try:
                    return self.coingecko_client.get_token_price(token_address)
                except CannotGetPrice:
                    pass
        return 0.



@app.shared_task()
def fix_pool_tokens_task() -> Optional[int]:
    ethereum_client = EthereumClientProvider()
    ethereum_network = ethereum_client.get_network()
    if ethereum_network == EthereumNetwork.MAINNET:
        try:
            number = Token.pool_tokens.fix_all_pool_tokens()
            if number:
                logger.info('%d pool token names were fixed', number)
            return number
        finally:
            close_gevent_db_connection()


def get_balance_service():
    if not hasattr(get_balance_service, 'instance'):
        get_balance_service.instance = BalanceAlternativeService(EthereumClientProvider(),
                                                                 get_redis(),
                                                                 settings.ETH_UNISWAP_FACTORY_ADDRESS,
                                                                 settings.ETH_KYBER_NETWORK_PROXY_ADDRESS)
    return get_balance_service.instance


@app.shared_task()
def calculate_token_eth_price(token_address: str, redis_key: str) -> Optional[float]:
    redis = get_redis()
    eth_price = get_balance_service().get_token_eth_value(token_address)
    print('price', eth_price)
    redis.setex(redis_key, 60 * 30, eth_price)  # Expire in 30 minutes
    return eth_price
