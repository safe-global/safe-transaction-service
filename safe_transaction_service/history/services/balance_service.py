import logging
import operator
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from typing import Iterator, List, Optional, Sequence

from django.db.models import Q
from django.utils import timezone

from cache_memoize import cache_memoize
from cachetools import cachedmethod
from eth_typing import ChecksumAddress
from redis import Redis
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.services.price_service import (
    PriceService, PriceServiceProvider)
from safe_transaction_service.tokens.tasks import (EthValueWithTimestamp,
                                                   calculate_token_eth_price)

from ..exceptions import NodeConnectionError
from ..models import EthereumEvent
from ..utils import get_redis

logger = logging.getLogger(__name__)


class BalanceServiceException(Exception):
    pass


@dataclass
class Erc20InfoWithLogo:
    address: ChecksumAddress
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
    token_address: Optional[ChecksumAddress]  # For ether, `token_address` is `None`
    token: Optional[Erc20InfoWithLogo]
    balance: int


@dataclass
class BalanceWithFiat(Balance):
    eth_value: float  # Value in ether
    timestamp: datetime  # Calculated timestamp
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

    def _filter_addresses(self, erc20_addresses: Sequence[ChecksumAddress],
                          only_trusted: bool, exclude_spam: bool) -> List[ChecksumAddress]:
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

    def get_balances(self, safe_address: ChecksumAddress,
                     only_trusted: bool = False, exclude_spam: bool = False) -> List[Balance]:
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

    def get_cached_token_eth_values(self,
                                    token_addresses: Sequence[ChecksumAddress]) -> Iterator[EthValueWithTimestamp]:
        """
        Get token eth prices with timestamp of calculation if ready on cache. If not, schedule tasks to do
        the calculation so next time is available on cache and return `0.` and current datetime
        :param token_addresses:
        :return: eth prices with timestamp if ready on cache, `0.` and None otherwise
        """
        cache_keys = [f'balance-service:{token_address}:eth-price' for token_address in token_addresses]
        results = self.redis.mget(cache_keys)  # eth_value:epoch_timestamp
        for token_address, cache_key, result in zip(token_addresses, cache_keys, results):
            if not token_address:  # Ether, this will not be used
                yield EthValueWithTimestamp(1., timezone.now())  # Even if not used, Ether value in ether is 1 :)
            elif result:
                yield EthValueWithTimestamp.from_string(result.decode())
            else:
                task_result = calculate_token_eth_price.delay(token_address, cache_key)
                if task_result.ready():
                    yield task_result.get()
                else:
                    yield EthValueWithTimestamp(0., timezone.now())

    @cachedmethod(cache=operator.attrgetter('cache_token_info'))
    @cache_memoize(60 * 60 * 24, prefix='balances-get_token_info')  # 1 day
    def get_token_info(self, token_address: ChecksumAddress) -> Optional[Erc20InfoWithLogo]:
        try:
            token = Token.objects.get(address=token_address)
            return Erc20InfoWithLogo.from_token(token)
        except Token.DoesNotExist:
            if token := Token.objects.create_from_blockchain(token_address):
                return Erc20InfoWithLogo.from_token(token)
            else:
                logger.warning('Cannot get erc20 token info for token-address=%s', token_address)
                return None

    def get_usd_balances(self, safe_address: ChecksumAddress, only_trusted: bool = False,
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
        eth_price = self.price_service.get_eth_usd_price()
        balances_with_usd = []
        token_addresses = [balance.token_address for balance in balances]
        token_eth_values_with_timestamp = self.get_cached_token_eth_values(token_addresses)
        for balance, token_eth_value_with_timestamp in zip(balances, token_eth_values_with_timestamp):
            token_eth_value = token_eth_value_with_timestamp.eth_value
            token_address = balance.token_address
            if not token_address:  # Ether
                fiat_conversion = eth_price
                fiat_balance = fiat_conversion * (balance.balance / 10**18)
            else:
                fiat_conversion = eth_price * token_eth_value
                balance_with_decimals = balance.balance / 10**balance.token.decimals
                fiat_balance = fiat_conversion * balance_with_decimals

            balances_with_usd.append(
                BalanceWithFiat(
                    balance.token_address,
                    balance.token,
                    balance.balance,
                    token_eth_value,
                    token_eth_value_with_timestamp.timestamp,
                    round(fiat_balance, 4),
                    round(fiat_conversion, 4),
                    'USD'
                )
            )

        return balances_with_usd
