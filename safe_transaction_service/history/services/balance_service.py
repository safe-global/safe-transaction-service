import logging
import operator
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from django.conf import settings
from django.core.cache import cache as django_cache
from django.db.models import Q

from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from eth_typing import ChecksumAddress
from redis import Redis
from safe_eth.eth import EthereumClient, get_auto_ethereum_client
from safe_eth.eth.utils import fast_is_checksum_address

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


class BalanceServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = BalanceService(get_auto_ethereum_client(), get_redis())
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
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[Balance], int]:
        """
        Get a list of balances including native token balance.
        For ether, `token_address` is `None`.
        Elements are cached for one hour

        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :param limit:
        :param offset:
        :return: a list of `{'token_address': str, 'balance': int}` and the number of different tokens for the providen Safe.
        """

        # Cache based on the number of erc20 events and the ether transferred, and also check outgoing ether
        # transactions that will not emit events on non L2 networks
        events_sending_eth = (
            MultisigTransaction.objects.ether_transfers()
            .executed()
            .filter(safe=safe_address)
            .count()
        )
        number_erc20_events = ERC20Transfer.objects.fast_count(safe_address)
        number_eth_events = InternalTx.objects.ether_txs_for_address(
            safe_address
        ).count()
        cache_key = (
            f"balances:{safe_address}:{only_trusted}:{exclude_spam}:{limit}:{offset}"
            f"{number_erc20_events}:{number_eth_events}:{events_sending_eth}"
        )
        cache_key_count = f"balances-count:{safe_address}:{only_trusted}:{exclude_spam}"
        if balances := django_cache.get(cache_key):
            count = django_cache.get(cache_key_count)
            return balances, count
        else:
            balances, count = self._get_balances(
                safe_address, only_trusted, exclude_spam, limit, offset
            )
            django_cache.set(cache_key, balances, 60 * 10)  # 10 minutes cache
            django_cache.set(cache_key_count, count, 60 * 10)  # 10 minutes cache
            return balances, count

    def _get_page_erc20_balances(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[ChecksumAddress], int]:
        """
        :param safe_address:
        :param only_trusted:
        :param exclude_spam:
        :param limit:
        :param offset:
        :return: List of ERC20 token addresses (paginated if `limit` is provided)
            and count of all ERC20 addresses for a given Safe
        """
        all_erc20_addresses = ERC20Transfer.objects.tokens_used_by_address(safe_address)
        for address in all_erc20_addresses:
            # Store tokens in database if not present
            self.get_token_info(address)  # This is cached
        erc20_addresses = self._filter_addresses(
            all_erc20_addresses, only_trusted, exclude_spam
        )
        # Total count should take into account the request filters
        erc20_count = len(erc20_addresses)

        if not limit:
            # No limit, no pagination
            return erc20_addresses, erc20_count

        if offset == 0:
            # First page will include also native token balance
            return erc20_addresses[offset : limit - 1], erc20_count
        else:
            # Include previous ERC20 after first page
            previous_offset = offset - 1
            return (
                erc20_addresses[previous_offset : previous_offset + limit],
                erc20_count,
            )

    def _get_balances(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[Balance], int]:
        """
        Get a list of balances including native token balance.
        For ether, `token_address` is `None`.
        Elements are cached for one hour

        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :param limit:
        :param offset:
        :return: a list of `{'token_address': str, 'balance': int}` and the number of different tokens for the providen Safe.
        """
        assert fast_is_checksum_address(
            safe_address
        ), f"Not valid address {safe_address} for getting balances"

        erc20_addresses_page, erc20_count = self._get_page_erc20_balances(
            safe_address, only_trusted, exclude_spam, limit, offset
        )

        try:
            raw_balances = []
            # With a lot of addresses an HTTP 413 error will be raised
            for erc20_addresses_chunk in chunks(
                erc20_addresses_page, settings.TOKENS_ERC20_GET_BALANCES_BATCH
            ):
                balances = self.ethereum_client.erc20.get_balances(
                    safe_address, erc20_addresses_chunk
                )

                # Skip ether transfer if already there
                raw_balances.extend(balances[1:] if raw_balances else balances)

            # Return ether balance if there are no tokens
            if not erc20_addresses_page:
                raw_balances = self.ethereum_client.erc20.get_balances(safe_address, [])
        except (IOError, ValueError) as exc:
            raise NodeConnectionException from exc

        balances = []
        if offset != 0 and raw_balances:
            # Remove ethereum balance if is not the first page
            raw_balances = raw_balances[1:]

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

        # Add Native token to the list
        count = erc20_count + 1
        return balances, count

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
