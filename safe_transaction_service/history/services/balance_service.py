import logging
import operator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Sequence

from django.conf import settings
from django.core.cache import cache as django_cache
from django.db.models import Q

from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from eth_typing import ChecksumAddress
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.utils import fast_is_checksum_address

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.utils import chunks

from ..exceptions import NodeConnectionException
from ..models import ERC20Transfer, InternalTx, MultisigTransaction

logger = logging.getLogger(__name__)


class BalanceServiceException(Exception):
    pass


@dataclass
class Erc20InfoWithLogo:
    address: ChecksumAddress
    name: str
    symbol: str
    decimals: int
    copy_price: Optional[ChecksumAddress]
    logo_uri: str

    @classmethod
    def from_token(cls, token: Token):
        return cls(
            token.address,
            token.name,
            token.symbol,
            token.decimals,
            token.copy_price,
            token.get_full_logo_uri(),
        )


@dataclass
class Balance:
    token_address: Optional[ChecksumAddress]  # For ether, `token_address` is `None`
    token: Optional[Erc20InfoWithLogo]
    balance: int

    def get_price_address(self) -> ChecksumAddress:
        """
        :return: Address to use to retrieve the token price
        """
        if self.token and self.token.copy_price:
            return self.token.copy_price
        return self.token_address


class FiatCode(Enum):
    USD = 1
    EUR = 2


@dataclass
class BalanceWithFiat(Balance):
    eth_value: float  # Value in ether
    timestamp: datetime  # Calculated timestamp
    fiat_balance: float
    fiat_conversion: float
    fiat_code: str = FiatCode.USD.name


class BalanceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = BalanceService(EthereumClientProvider(), get_redis())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class BalanceService:
    def __init__(self, ethereum_client: EthereumClient, redis: Redis):
        self.ethereum_client = ethereum_client
        self.ethereum_network = self.ethereum_client.get_network()
        self.redis = redis
        self.cache_token_info = TTLCache(
            maxsize=4096, ttl=60 * 30
        )  # 2 hours of caching

    def _filter_addresses(
        self,
        erc20_addresses: Sequence[ChecksumAddress],
        only_trusted: bool,
        exclude_spam: bool,
    ) -> List[ChecksumAddress]:
        """
        :param erc20_addresses:
        :param only_trusted:
        :param exclude_spam:
        :return: ERC20 tokens filtered by spam or trusted
        """
        base_queryset = Token.objects.filter(
            Q(address__in=erc20_addresses) | Q(events_bugged=True)
        ).order_by("name")
        if only_trusted:
            addresses = list(
                base_queryset.erc20()
                .filter(trusted=True)
                .values_list("address", flat=True)
            )
        elif exclude_spam:
            addresses = list(
                base_queryset.erc20()
                .filter(spam=False)
                .values_list("address", flat=True)
            )
        else:
            # There could be some addresses that are not in the list
            addresses_set = set(erc20_addresses)
            addresses = []
            for token in base_queryset:
                if token.is_erc20():
                    addresses.append(token.address)
                if (
                    token.address in addresses_set
                ):  # events_bugged tokens might not be on the `addresses_set`
                    addresses_set.remove(token.address)
            # Add unknown addresses
            addresses.extend(addresses_set)

        return addresses

    def get_balances(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
    ):
        """
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`. Elements are cached
        for one hour
        """

        # Cache based on the number of erc20 events and the ether transferred, and also check outgoing ether
        # transactions that will not emit events on non L2 networks
        events_sending_eth = (
            MultisigTransaction.objects.ether_transfers()
            .executed()
            .filter(safe=safe_address)
            .count()
        )
        number_erc20_events = ERC20Transfer.objects.to_or_from(safe_address).count()
        number_eth_events = InternalTx.objects.ether_txs_for_address(
            safe_address
        ).count()
        cache_key = (
            f"balances:{safe_address}:{only_trusted}:{exclude_spam}:"
            f"{number_erc20_events}:{number_eth_events}:{events_sending_eth}"
        )
        if balances := django_cache.get(cache_key):
            return balances
        else:
            balances = self._get_balances(safe_address, only_trusted, exclude_spam)
            django_cache.set(cache_key, balances, 60 * 10)  # 10 minutes cache
            return balances

    def _get_balances(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
    ) -> List[Balance]:
        """
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`
        """
        assert fast_is_checksum_address(
            safe_address
        ), f"Not valid address {safe_address} for getting balances"

        all_erc20_addresses = ERC20Transfer.objects.tokens_used_by_address(safe_address)
        for address in all_erc20_addresses:
            # Store tokens in database if not present
            self.get_token_info(address)  # This is cached
        erc20_addresses = self._filter_addresses(
            all_erc20_addresses, only_trusted, exclude_spam
        )

        try:
            raw_balances = []
            # With a lot of addresses an HTTP 413 error will be raised
            for erc20_addresses_chunk in chunks(
                erc20_addresses, settings.TOKENS_ERC20_GET_BALANCES_BATCH
            ):
                balances = self.ethereum_client.erc20.get_balances(
                    safe_address, erc20_addresses_chunk
                )

                # Skip ether transfer if already there
                raw_balances.extend(balances[1:] if raw_balances else balances)

            # Return ether balance if there are no tokens
            if not raw_balances:
                raw_balances = self.ethereum_client.erc20.get_balances(safe_address, [])
            # First element should be the ether transfer
        except (IOError, ValueError) as exc:
            raise NodeConnectionException from exc

        balances = []
        for balance in raw_balances:
            if not balance["token_address"]:  # Ether
                balance["token"] = None
            elif balance["balance"] > 0:
                balance["token"] = self.get_token_info(balance["token_address"])
                if not balance["token"]:  # Ignore ERC20 tokens that cannot be queried
                    continue
            else:
                continue
            balances.append(Balance(**balance))
        return balances

    @cachedmethod(cache=operator.attrgetter("cache_token_info"))
    @cache_memoize(60 * 60, prefix="balances-get_token_info")  # 1 hour
    def get_token_info(
        self, token_address: ChecksumAddress
    ) -> Optional[Erc20InfoWithLogo]:
        try:
            token = Token.objects.get(address=token_address)
            return Erc20InfoWithLogo.from_token(token)
        except Token.DoesNotExist:
            if token := Token.objects.create_from_blockchain(token_address):
                return Erc20InfoWithLogo.from_token(token)
            else:
                logger.warning(
                    "Cannot get erc20 token info for token-address=%s", token_address
                )
                return None

    def get_usd_balances(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
    ) -> List[BalanceWithFiat]:
        """
        NOTE: PriceService was removed, this function return balances with price 0.

        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return: List of BalanceWithFiat
        """
        balances: List[Balance] = self.get_balances(
            safe_address, only_trusted, exclude_spam
        )
        balances_with_usd = []

        for balance in balances:
            balances_with_usd.append(
                BalanceWithFiat(
                    balance.token_address,
                    balance.token,
                    balance.balance,
                    0.0,
                    datetime.utcfromtimestamp(0),
                    0.0,
                    0.0,
                    FiatCode.USD.name,
                )
            )

        return balances_with_usd
