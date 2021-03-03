import logging
import operator
from dataclasses import dataclass
from functools import cached_property
from typing import List, Optional, Sequence

from django.db.models import Q

from cache_memoize import cache_memoize
from cachetools import cachedmethod
from redis import Redis
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.ethereum_client import InvalidERC20Info

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.services.price_service import (
    PriceService, PriceServiceProvider)
from safe_transaction_service.tokens.tasks import calculate_token_eth_price

from ..exceptions import NodeConnectionError
from ..models import EthereumEvent
from ..utils import get_redis

logger = logging.getLogger(__name__)


class BalanceServiceException(Exception):
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
            cls.instance = BalanceService(EthereumClientProvider(), PriceServiceProvider(), get_redis())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, 'instance'):
            del cls.instance


class BalanceService:
    def __init__(self, ethereum_client: EthereumClient, price_service: PriceService, redis: Redis):
        self.ethereum_client = ethereum_client
        self.price_service = price_service
        self.redis = redis
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
            Q(address__in=erc20_addresses) | Q(events_bugged=True)
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
                if token.address in addresses_set:  # events_bugged tokens might not be on the `addresses_set`
                    addresses_set.remove(token.address)
            # Add unknown addresses
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

        try:
            raw_balances = self.ethereum_client.erc20.get_balances(safe_address, erc20_addresses)
        except IOError as exc:
            raise NodeConnectionError from exc

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

    def get_cached_token_eth_value(self, token_address: str) -> float:
        """
        Get token eth price if ready on cache. If not, schedule a task to do the calculation so next time is available
        on cache and return 0 (unless calculation is ready))
        :param token_address:
        :return: eth price if ready on cache, `0` otherwise
        """
        cache_key = f'balance-service:{token_address}:eth-price'
        if eth_value := self.redis.get(cache_key):
            return float(eth_value)
        else:
            result = calculate_token_eth_price.delay(token_address, cache_key)
            if result.ready():
                return float(result.get())
            else:
                return 0.0

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
        eth_value = self.price_service.get_eth_price()
        balances_with_usd = []
        for balance in balances:
            token_address = balance.token_address
            if not token_address:  # Ether
                fiat_conversion = eth_value
                fiat_balance = fiat_conversion * (balance.balance / 10**18)
            else:
                token_to_eth_price = self.get_cached_token_eth_value(token_address)
                if token_to_eth_price:
                    fiat_conversion = eth_value * token_to_eth_price
                else:  # Use curve/coingecko as last resource
                    fiat_conversion = self.price_service.get_token_usd_price(token_address)

                balance_with_decimals = balance.balance / 10**balance.token.decimals
                fiat_balance = fiat_conversion * balance_with_decimals

            balances_with_usd.append(BalanceWithFiat(balance.token_address,
                                                     balance.token,
                                                     balance.balance,
                                                     round(fiat_balance, 4),
                                                     round(fiat_conversion, 4),
                                                     'USD'))

        return balances_with_usd
