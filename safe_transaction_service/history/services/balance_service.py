import logging
import operator
from dataclasses import dataclass
from functools import cached_property
from typing import List, Optional, Sequence

import requests
from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from requests.exceptions import ConnectionError
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetwork, InvalidERC20Info
from gnosis.eth.oracles import (KyberOracle, OracleException, UniswapOracle,
                                UniswapV2Oracle)

from safe_transaction_service.tokens.models import Token

from ..models import EthereumEvent

logger = logging.getLogger(__name__)


class BalanceServiceException(Exception):
    pass


class CannotGetEthereumPrice(BalanceServiceException):
    pass


@dataclass
class Erc20InfoWithLogo:
    address: str
    name: str
    symbol: str
    decimals: int
    logo_uri: str

    @classmethod
    def from_token(cls, token: Token):
        return cls(token.address,
                   token.name,
                   token.symbol,
                   token.decimals,
                   token.get_full_logo_uri())


@dataclass
class Balance:
    token_address: Optional[str]  # For ether, `token_address` is `None`
    token: Optional[Erc20InfoWithLogo]
    balance: int


@dataclass
class BalanceWithFiat(Balance):
    fiat_balance: float
    fiat_conversion: float
    fiat_code: str = 'USD'


class BalanceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = BalanceService(EthereumClientProvider(),
                                          settings.ETH_UNISWAP_FACTORY_ADDRESS,
                                          settings.ETH_KYBER_NETWORK_PROXY_ADDRESS)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class BalanceService:
    def __init__(self, ethereum_client: EthereumClient,
                 uniswap_factory_address: str, kyber_network_proxy_address: str):
        self.ethereum_client = ethereum_client
        self.uniswap_oracle = UniswapOracle(self.ethereum_client, uniswap_factory_address)
        self.uniswap_v2_oracle = UniswapV2Oracle(self.ethereum_client)
        self.kyber_oracle = KyberOracle(self.ethereum_client, kyber_network_proxy_address)
        self.cache_eth_price = TTLCache(maxsize=2048, ttl=60 * 30)  # 30 minutes of caching
        self.cache_token_eth_value = TTLCache(maxsize=2048, ttl=60 * 30)  # 30 minutes of caching
        self.cache_token_info = {}

    @cached_property
    def ethereum_network(self):
        return self.ethereum_client.get_network()

    def _filter_addresses(self, erc20_addresses: Sequence[str], only_trusted: bool, exclude_spam: bool) -> List[str]:
        """
        :param erc20_addresses:
        :param only_trusted:
        :param exclude_spam:
        :return: ERC20 tokens filtered by spam or trusted
        """
        base_queryset = Token.objects.filter(
            address__in=erc20_addresses
        ).order_by('name')
        if only_trusted:
            addresses = list(base_queryset.erc20().filter(trusted=True).values_list('address', flat=True))
        elif exclude_spam:
            addresses = list(base_queryset.erc20().filter(spam=False).values_list('address', flat=True))
        else:
            # There could be some addresses that are not in the list
            addresses_set = set(erc20_addresses)
            addresses = []
            for token in base_queryset:
                if token.is_erc20():
                    addresses.append(token.address)
                addresses_set.remove(token.address)
            # Add unkown addresses
            addresses.extend(addresses_set)

        return addresses

    def get_balances(self, safe_address: str, only_trusted: bool = False, exclude_spam: bool = False) -> List[Balance]:
        """
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`
        """
        assert Web3.isChecksumAddress(safe_address), f'Not valid address {safe_address} for getting balances'

        all_erc20_addresses = list(EthereumEvent.objects.erc20_tokens_used_by_address(safe_address))
        for address in all_erc20_addresses:
            # Store tokens in database if not present
            self.get_token_info(address)  # This is cached
        erc20_addresses = self._filter_addresses(all_erc20_addresses, only_trusted, exclude_spam)
        raw_balances = self.ethereum_client.erc20.get_balances(safe_address, erc20_addresses)

        balances = []
        for balance in raw_balances:
            if not balance['token_address']:  # Ether
                balance['token'] = None
            elif balance['balance'] > 0:
                balance['token'] = self.get_token_info(balance['token_address'])
                if not balance['token']:  # Ignore ERC20 tokens that cannot be queried
                    continue
            else:
                continue
            balances.append(Balance(**balance))
        return balances

    def _get_binance_price(self, symbol: str):
        url = f'https://api.binance.com/api/v3/avgPrice?symbol={symbol}'
        try:
            response = requests.get(url)
            api_json = response.json()
            if not response.ok:
                logger.warning('Cannot get price from url=%s', url)
                raise CannotGetEthereumPrice(api_json.get('msg'))

            price = float(api_json['price'])
            if not price:
                raise CannotGetEthereumPrice(f'Price from url={url} is {price}')
            return price
        except (ValueError, ConnectionError) as e:
            raise CannotGetEthereumPrice from e

    def _get_kraken_price(self, symbol: str):
        url = f'https://api.kraken.com/0/public/Ticker?pair={symbol}'
        try:
            response = requests.get(url)
            api_json = response.json()
            error = api_json.get('error')
            if not response.ok or error:
                logger.warning('Cannot get price from url=%s', url)
                raise CannotGetEthereumPrice(str(api_json['error']))

            result = api_json['result']
            for new_ticker in result:
                price = float(result[new_ticker]['c'][0])
                if not price:
                    raise CannotGetEthereumPrice(f'Price from url={url} is {price}')
                return price
        except (ValueError, ConnectionError) as e:
            raise CannotGetEthereumPrice from e

    def get_dai_usd_price_kraken(self) -> float:
        """
        :return: current USD price for ethereum using Kraken
        :raises: CannotGetEthereumPrice
        """
        return self._get_kraken_price('DAIUSD')

    def get_eth_usd_price_binance(self) -> float:
        """
        :return: current USD price for ethereum using Kraken
        :raises: CannotGetEthereumPrice
        """
        return self._get_binance_price('ETHUSDT')

    def get_eth_usd_price_kraken(self) -> float:
        """
        :return: current USD price for ethereum using Kraken
        :raises: CannotGetEthereumPrice
        """
        return self._get_kraken_price('ETHUSD')

    def get_ewt_usd_price_kucoin(self) -> float:
        url = 'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=EWT-USDT'
        response = requests.get(url)
        try:
            result = response.json()
            return float(result['data']['price'])
        except (ValueError, ConnectionError) as e:
            raise CannotGetEthereumPrice from e

    @cachedmethod(cache=operator.attrgetter('cache_eth_price'))
    @cache_memoize(60 * 30, prefix='balances-get_eth_price')  # 30 minutes
    def get_eth_price(self) -> float:
        """
        Get USD price for Ether. On xDAI we use DAI price.
        :return: USD price for Ether
        """
        if self.ethereum_network == EthereumNetwork.XDAI:
            try:
                return self.get_dai_usd_price_kraken()
            except CannotGetEthereumPrice:
                return 1  # DAI/USD should be close to 1
        elif self.ethereum_network in (EthereumNetwork.ENERGY_WEB_CHAIN, EthereumNetwork.VOLTA):
            return self.get_ewt_usd_price_kucoin()
        else:
            try:
                return self.get_eth_usd_price_kraken()
            except CannotGetEthereumPrice:
                return self.get_eth_usd_price_binance()

    @cachedmethod(cache=operator.attrgetter('cache_token_eth_value'))
    @cache_memoize(60 * 30, prefix='balances-get_token_eth_value')  # 30 minutes
    def get_token_eth_value(self, token_address: str) -> float:
        """
        Return current ether value for a given `token_address`
        """
        try:
            return self.kyber_oracle.get_price(token_address)
        except OracleException:
            logger.warning('Cannot get eth value for token-address=%s from Kyber, trying Uniswap V2', token_address)

        try:
            return self.uniswap_v2_oracle.get_price(token_address)
        except OracleException:
            logger.warning('Cannot get eth value for token-address=%s on Uniswap V2, trying Uniswap', token_address)

        try:
            return self.uniswap_oracle.get_price(token_address)
        except OracleException:
            logger.warning('Cannot get eth value for token-address=%s on Uniswap', token_address)
            return 0.

    @cachedmethod(cache=operator.attrgetter('cache_token_info'))
    @cache_memoize(60 * 60 * 24, prefix='balances-get_token_info')  # 1 day
    def get_token_info(self, token_address: str) -> Optional[Erc20InfoWithLogo]:
        try:
            token = Token.objects.get(address=token_address)
            return Erc20InfoWithLogo.from_token(token)
        except Token.DoesNotExist:
            try:
                erc20_info = self.ethereum_client.erc20.get_info(token_address)
                token = Token.objects.create(address=token_address,
                                             name=erc20_info.name,
                                             symbol=erc20_info.symbol,
                                             decimals=erc20_info.decimals)
                return Erc20InfoWithLogo.from_token(token)
            except InvalidERC20Info:
                logger.warning('Cannot get erc20 token info for token-address=%s', token_address)
                return None

    def get_usd_balances(self, safe_address: str, only_trusted: bool = False,
                         exclude_spam: bool = False) -> List[BalanceWithFiat]:
        """
        All this could be more optimal (e.g. batching requests), but as everything is cached
        I think we should be alright
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return: List of BalanceWithFiat
        """
        balances: List[Balance] = self.get_balances(safe_address, only_trusted, exclude_spam)
        eth_value = self.get_eth_price()
        balances_with_usd = []
        for balance in balances:
            token_address = balance.token_address
            if not token_address:  # Ether
                fiat_conversion = eth_value
                fiat_balance = fiat_conversion * (balance.balance / 10**18)
            else:
                token_to_eth_price = self.get_token_eth_value(token_address)
                if token_to_eth_price:
                    fiat_conversion = eth_value * token_to_eth_price
                    balance_with_decimals = balance.balance / 10**balance.token.decimals
                    fiat_balance = fiat_conversion * balance_with_decimals
                else:
                    fiat_conversion = 0.
                    fiat_balance = 0.

            balances_with_usd.append(BalanceWithFiat(balance.token_address,
                                                     balance.token,
                                                     balance.balance,
                                                     round(fiat_balance, 4),
                                                     round(fiat_conversion, 4),
                                                     'USD'))

        return balances_with_usd
