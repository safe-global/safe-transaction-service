import operator
from functools import cached_property
from typing import Tuple

from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from celery.utils.log import get_task_logger
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork
from gnosis.eth.oracles import (BalancerOracle, CannotGetPriceFromOracle,
                                CurveOracle, KyberOracle, MooniswapOracle,
                                OracleException, SushiswapOracle,
                                UniswapOracle, UniswapV2Oracle)
from gnosis.eth.oracles.oracles import PriceOracle, PricePoolOracle

from safe_transaction_service.history.utils import get_redis

from ..clients import (BinanceClient, CannotGetPrice, CoingeckoClient,
                       KrakenClient, KucoinClient)

logger = get_task_logger(__name__)


class PriceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = PriceService(EthereumClientProvider(), get_redis())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, 'instance'):
            del cls.instance


class PriceService:
    def __init__(self, ethereum_client: EthereumClient, redis: Redis):
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.binance_client = BinanceClient()
        self.coingecko_client = CoingeckoClient()
        self.kraken_client = KrakenClient()
        self.kucoin_client = KucoinClient()
        self.curve_oracle = CurveOracle(self.ethereum_client)  # Curve returns price in usd
        self.kyber_oracle = KyberOracle(self.ethereum_client)
        self.sushiswap_oracle = SushiswapOracle(self.ethereum_client)
        self.uniswap_oracle = UniswapOracle(self.ethereum_client)
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

    def get_ewt_usd_price(self) -> float:
        try:
            return self.kucoin_client.get_ewt_usd_price()
        except CannotGetPrice:
            return self.coingecko_client.get_ewt_usd_price()

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

    @cachedmethod(cache=operator.attrgetter('cache_token_eth_value'))
    @cache_memoize(60 * 30, prefix='balances-get_token_eth_value')  # 30 minutes
    def get_token_eth_value(self, token_address: str) -> float:
        """
        Uses multiple decentralized and centralized oracles to get token prices
        :param token_address:
        :return: Current ether value for a given `token_address`
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
