import operator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import Iterator, List, Optional, Sequence, Tuple

from django.utils import timezone

from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from celery.utils.log import get_task_logger
from eth_typing import ChecksumAddress
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.ethereum_client import EthereumNetwork
from gnosis.eth.oracles import (
    AaveOracle,
    BalancerOracle,
    ComposedPriceOracle,
    CurveOracle,
    EnzymeOracle,
    KyberOracle,
    MooniswapOracle,
    OracleException,
    PoolTogetherOracle,
    PriceOracle,
    PricePoolOracle,
    SushiswapOracle,
    UnderlyingToken,
    UniswapOracle,
    UniswapV2Oracle,
    YearnOracle,
)

from safe_transaction_service.utils.redis import get_redis

from ..clients import (
    BinanceClient,
    CannotGetPrice,
    CoingeckoClient,
    KrakenClient,
    KucoinClient,
)
from ..tasks import EthValueWithTimestamp, calculate_token_eth_price_task

logger = get_task_logger(__name__)


class FiatCode(Enum):
    USD = 1
    EUR = 2


@dataclass
class FiatPriceWithTimestamp:
    fiat_price: float
    fiat_code: FiatCode
    timestamp: datetime


class PriceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = PriceService(EthereumClientProvider(), get_redis())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class PriceService:
    def __init__(self, ethereum_client: EthereumClient, redis: Redis):
        self.ethereum_client = ethereum_client
        self.ethereum_network = self.ethereum_client.get_network()
        self.redis = redis
        self.binance_client = BinanceClient()
        self.coingecko_client = CoingeckoClient(self.ethereum_network)
        self.curve_oracle = CurveOracle(self.ethereum_client)
        self.kraken_client = KrakenClient()
        self.kucoin_client = KucoinClient()
        self.kyber_oracle = KyberOracle(self.ethereum_client)
        self.sushiswap_oracle = SushiswapOracle(self.ethereum_client)
        self.uniswap_oracle = UniswapOracle(self.ethereum_client)
        self.uniswap_v2_oracle = UniswapV2Oracle(self.ethereum_client)
        self.pool_together_oracle = PoolTogetherOracle(self.ethereum_client)
        self.yearn_oracle = YearnOracle(self.ethereum_client)
        self.enzyme_oracle = EnzymeOracle(self.ethereum_client)
        self.aave_oracle = AaveOracle(self.ethereum_client, self.uniswap_v2_oracle)
        self.balancer_oracle = BalancerOracle(
            self.ethereum_client, self.uniswap_v2_oracle
        )
        self.mooniswap_oracle = MooniswapOracle(
            self.ethereum_client, self.uniswap_v2_oracle
        )
        self.cache_eth_price = TTLCache(
            maxsize=2048, ttl=60 * 30
        )  # 30 minutes of caching
        self.cache_token_eth_value = TTLCache(
            maxsize=2048, ttl=60 * 30
        )  # 30 minutes of caching
        self.cache_token_usd_value = TTLCache(
            maxsize=2048, ttl=60 * 30
        )  # 30 minutes of caching
        self.cache_underlying_token = TTLCache(
            maxsize=2048, ttl=60 * 30
        )  # 30 minutes of caching
        self.cache_token_info = {}

    @cached_property
    def enabled_price_oracles(self) -> Tuple[PriceOracle]:
        if self.ethereum_network == EthereumNetwork.MAINNET:
            return (
                self.uniswap_v2_oracle,
                self.sushiswap_oracle,
                self.uniswap_oracle,
                self.aave_oracle,
                self.kyber_oracle,
            )
        else:
            return (
                self.uniswap_v2_oracle,
                self.kyber_oracle,
            )  # There are versions in another networks

    @cached_property
    def enabled_price_pool_oracles(self) -> Tuple[PricePoolOracle]:
        if self.ethereum_network == EthereumNetwork.MAINNET:
            return self.uniswap_v2_oracle, self.balancer_oracle, self.mooniswap_oracle
        else:
            return tuple()

    @cached_property
    def enabled_composed_price_oracles(self) -> Tuple[ComposedPriceOracle]:
        if self.ethereum_network == EthereumNetwork.MAINNET:
            return (
                self.curve_oracle,
                self.yearn_oracle,
                self.pool_together_oracle,
                self.enzyme_oracle,
            )
        else:
            return tuple()

    def get_avalanche_usd_price(self) -> float:
        try:
            return self.kraken_client.get_avax_usd_price()
        except CannotGetPrice:
            return self.coingecko_client.get_avax_usd_price()

    def get_aurora_usd_price(self) -> float:
        return self.coingecko_client.get_aoa_usd_price()

    def get_binance_usd_price(self) -> float:
        try:
            return self.binance_client.get_bnb_usd_price()
        except CannotGetPrice:
            return self.coingecko_client.get_bnb_usd_price()

    def get_ewt_usd_price(self) -> float:
        try:
            return self.kraken_client.get_ewt_usd_price()
        except CannotGetPrice:
            try:
                return self.kucoin_client.get_ewt_usd_price()
            except CannotGetPrice:
                return self.coingecko_client.get_ewt_usd_price()

    def get_matic_usd_price(self) -> float:
        try:
            return self.kraken_client.get_matic_usd_price()
        except CannotGetPrice:
            try:
                return self.binance_client.get_matic_usd_price()
            except CannotGetPrice:
                return self.coingecko_client.get_matic_usd_price()

    @cachedmethod(cache=operator.attrgetter("cache_eth_price"))
    @cache_memoize(60 * 30, prefix="balances-get_eth_usd_price")  # 30 minutes
    def get_native_coin_usd_price(self) -> float:
        """
        Get USD price for native coin. It depends on the ethereum network:
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
        elif self.ethereum_network in (
            EthereumNetwork.ENERGY_WEB_CHAIN,
            EthereumNetwork.VOLTA,
        ):
            return self.get_ewt_usd_price()
        elif self.ethereum_network in (EthereumNetwork.MATIC, EthereumNetwork.MUMBAI):
            return self.get_matic_usd_price()
        elif self.ethereum_network == EthereumNetwork.BINANCE:
            return self.get_binance_usd_price()
        elif self.ethereum_network in (
            EthereumNetwork.GATHER_DEVNET,
            EthereumNetwork.GATHER_TESTNET,
            EthereumNetwork.GATHER_MAINNET,
        ):
            return self.coingecko_client.get_gather_usd_price()
        elif self.ethereum_network == EthereumNetwork.AVALANCHE:
            return self.get_avalanche_usd_price()
        elif self.ethereum_network in (
            EthereumNetwork.AURORA,
            EthereumNetwork.AURORA_BETANET,
            EthereumNetwork.ARBITRUM_TESTNET,
        ):
            return self.get_aurora_usd_price()
        else:
            try:
                return self.kraken_client.get_eth_usd_price()
            except CannotGetPrice:
                return self.binance_client.get_eth_usd_price()

    @cachedmethod(cache=operator.attrgetter("cache_token_eth_value"))
    @cache_memoize(60 * 30, prefix="balances-get_token_eth_value")  # 30 minutes
    def get_token_eth_value(self, token_address: ChecksumAddress) -> float:
        """
        Uses multiple decentralized and centralized oracles to get token prices

        :param token_address:
        :return: Current ether value for a given `token_address`
        """
        if token_address in (
            "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",  # Used by some oracles
            NULL_ADDRESS,
        ):  # Ether
            return 1.0

        for oracle in self.enabled_price_oracles:
            try:
                return oracle.get_price(token_address)
            except OracleException:
                logger.info(
                    "Cannot get eth value for token-address=%s from %s",
                    token_address,
                    oracle.__class__.__name__,
                )

        # Try pool tokens
        for oracle in self.enabled_price_pool_oracles:
            try:
                return oracle.get_pool_token_price(token_address)
            except OracleException:
                logger.info(
                    "Cannot get eth value for token-address=%s from %s",
                    token_address,
                    oracle.__class__.__name__,
                )

        logger.warning("Cannot find eth value for token-address=%s", token_address)
        return 0.0

    @cachedmethod(cache=operator.attrgetter("cache_token_usd_value"))
    @cache_memoize(60 * 30, prefix="balances-get_token_usd_price")  # 30 minutes
    def get_token_usd_price(self, token_address: ChecksumAddress) -> float:
        """
        :param token_address:
        :return: usd value for a given `token_address` using Curve, if not use Coingecko as last resource
        """
        if self.coingecko_client.supports_network(EthereumNetwork.MAINNET):
            try:
                return self.coingecko_client.get_token_price(token_address)
            except CannotGetPrice:
                pass
        return 0.0

    @cachedmethod(cache=operator.attrgetter("cache_underlying_token"))
    @cache_memoize(60 * 30, prefix="balances-get_underlying_tokens")  # 30 minutes
    def get_underlying_tokens(
        self, token_address: ChecksumAddress
    ) -> Optional[List[UnderlyingToken]]:
        """
        :param token_address:
        :return: usd value for a given `token_address` using Curve, if not use Coingecko as last resource
        """
        for oracle in self.enabled_composed_price_oracles:
            try:
                return oracle.get_underlying_tokens(token_address)
            except OracleException:
                logger.info(
                    "Cannot get an underlying token for token-address=%s from %s",
                    token_address,
                    oracle.__class__.__name__,
                )

    def get_cached_token_eth_values(
        self, token_addresses: Sequence[ChecksumAddress]
    ) -> Iterator[EthValueWithTimestamp]:
        """
        Get token eth prices with timestamp of calculation if ready on cache. If not, schedule tasks to do
        the calculation so next time is available on cache and return `0.` and current datetime

        :param token_addresses:
        :return: eth prices with timestamp if ready on cache, `0.` and None otherwise
        """
        cache_keys = [
            f"price-service:{token_address}:eth-price"
            for token_address in token_addresses
        ]
        results = self.redis.mget(cache_keys)  # eth_value:epoch_timestamp
        for token_address, cache_key, result in zip(
            token_addresses, cache_keys, results
        ):
            if not token_address:  # Ether, this will not be used
                yield EthValueWithTimestamp(
                    1.0, timezone.now()
                )  # Even if not used, Ether value in ether is 1 :)
            elif result:
                yield EthValueWithTimestamp.from_string(result.decode())
            else:
                task_result = calculate_token_eth_price_task.delay(
                    token_address, cache_key
                )
                if task_result.ready():
                    yield task_result.get()
                else:
                    yield EthValueWithTimestamp(0.0, timezone.now())

    def get_cached_usd_values(
        self, token_addresses: Sequence[ChecksumAddress]
    ) -> Iterator[FiatPriceWithTimestamp]:
        """
        Get token usd prices with timestamp of calculation if ready on cache.

        :param token_addresses:
        :return: eth prices with timestamp if ready on cache, `0.` and None otherwise
        """
        try:
            eth_price = self.get_native_coin_usd_price()
        except CannotGetPrice:
            logger.warning("Cannot get network ether price", exc_info=True)
            eth_price = 0

        for token_eth_values_with_timestamp in self.get_cached_token_eth_values(
            token_addresses
        ):
            yield FiatPriceWithTimestamp(
                eth_price * token_eth_values_with_timestamp.eth_value,
                FiatCode.USD,
                token_eth_values_with_timestamp.timestamp,
            )
