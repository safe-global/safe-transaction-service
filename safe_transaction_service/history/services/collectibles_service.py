import logging
import operator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from django.db.models import Q

import requests
from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_transaction_service.tokens.constants import (
    CRYPTO_KITTIES_CONTRACT_ADDRESSES, ENS_CONTRACTS_WITH_TLD)
from safe_transaction_service.tokens.models import Token

from ..clients import EnsClient
from ..exceptions import NodeConnectionError
from ..models import EthereumEvent

logger = logging.getLogger(__name__)


class CollectiblesServiceException(Exception):
    pass


class MetadataRetrievalException(CollectiblesServiceException):
    pass


@dataclass
class Erc721InfoWithLogo:
    address: str
    name: str
    symbol: str
    logo_uri: str

    @classmethod
    def from_token(cls, token: Token, logo_uri: Optional[str] = None):
        return cls(token.address,
                   token.name,
                   token.symbol,
                   logo_uri if logo_uri else token.get_full_logo_uri())


@dataclass
class Collectible:
    token_name: str
    token_symbol: str
    logo_uri: str
    address: str
    id: int
    uri: str


@dataclass
class CollectibleWithMetadata(Collectible):
    metadata: Dict[str, Any]
    name: Optional[str] = field(init=False)
    description: Optional[str] = field(init=False)
    image_uri: Optional[str] = field(init=False)

    def get_name(self) -> Optional[str]:
        if self.metadata:
            for key in ('name',):
                if key in self.metadata:
                    return self.metadata[key]

    def get_description(self) -> Optional[str]:
        if self.metadata:
            for key in ('description',):
                if key in self.metadata:
                    return self.metadata[key]

    def get_metadata_image(self) -> Optional[str]:
        if not self.metadata:
            return None

        for key in ('image', 'image_url', 'image_uri', 'imageUri', 'imageUrl'):
            if key in self.metadata:
                return self.metadata[key]

        for key, value in self.metadata.items():
            if (key.lower().startswith('image')
                    and isinstance(self.metadata[key], str)
                    and self.metadata[key].startswith('http')):
                return self.metadata[key]

    def __post_init__(self):
        self.name = self.get_name()
        self.description = self.get_description()
        self.image_uri = self.get_metadata_image()


class CollectiblesServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = CollectiblesService(EthereumClientProvider())

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class CollectiblesService:
    ENS_IMAGE_URL = 'https://gnosis-safe-token-logos.s3.amazonaws.com/ENS.png'
    IPFS_GATEWAY = 'https://cloudflare-ipfs.com/'

    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        self.ens_service: EnsClient = EnsClient(ethereum_client.get_network().value)

        self.cache_uri_metadata = TTLCache(maxsize=1024, ttl=60 * 60 * 24)  # 1 day of caching
        self.cache_token_info: Dict[str, Tuple[str, str]] = {}
        self.cache_token_uri: Dict[Tuple[str, int], str] = {}
        self.http_session = requests.session()

    @cachedmethod(cache=operator.attrgetter('cache_uri_metadata'))
    @cache_memoize(60 * 60 * 24, prefix='collectibles-_retrieve_metadata_from_uri')  # 1 day
    def _retrieve_metadata_from_uri(self, uri: str) -> Dict[Any, Any]:
        """
        Get metadata from uri. Maybe at some point support IPFS or another protocols. Currently just http/https is
        supported
        :param uri: Uri starting with the protocol, like http://example.org/token/3
        :return: Metadata as a decoded json
        """
        if uri and uri.startswith('ipfs://'):
            uri = urljoin(self.IPFS_GATEWAY, uri.replace('ipfs://', ''))  # Use ipfs gateway

        if not uri or not uri.startswith('http'):
            raise MetadataRetrievalException(uri)

        try:
            logger.debug('Getting metadata for uri=%s', uri)
            response = self.http_session.get(uri)
            if not response.ok:
                logger.debug('Cannot get metadata for uri=%s', uri)
                raise MetadataRetrievalException(uri)
            else:
                logger.debug('Got metadata for uri=%s', uri)
                return response.json()
        except (requests.RequestException, ValueError) as e:
            raise MetadataRetrievalException(uri) from e

    def build_collectible(self, token_info: Optional[Erc721InfoWithLogo], token_address: str, token_id: int,
                          token_metadata_uri: Optional[str]) -> Collectible:
        if not token_metadata_uri:
            if token_address in CRYPTO_KITTIES_CONTRACT_ADDRESSES:
                token_metadata_uri = f'https://api.cryptokitties.co/kitties/{token_id}'
            else:
                logger.info('Not available token_uri to retrieve metadata for ERC721 token=%s with token-id=%d',
                            token_address, token_id)
        name = token_info.name if token_info else ''
        symbol = token_info.symbol if token_info else ''
        logo_uri = token_info.logo_uri if token_info else ''
        return Collectible(name, symbol, logo_uri, token_address, token_id, token_metadata_uri)

    def get_metadata(self, collectible: Collectible) -> Dict[Any, Any]:
        if tld := ENS_CONTRACTS_WITH_TLD.get(collectible.address):  # Special case for ENS
            label_name = self.ens_service.query_by_domain_hash(collectible.id)
            return {
                'name': f'{label_name}.{tld}' if label_name else f'.{tld}',
                'description': ('' if label_name else 'Unknown ') + f'.{tld} ENS Domain',
                'image': self.ENS_IMAGE_URL,
            }

        return self._retrieve_metadata_from_uri(collectible.uri)

    def _filter_addresses(self, addresses_with_token_ids: Sequence[Tuple[str, int]],
                          only_trusted: bool = False, exclude_spam: bool = False):
        """
        :param addresses_with_token_ids:
        :param only_trusted:
        :param exclude_spam:
        :return: ERC721 tokens filtered by spam or trusted
        """
        addresses_set = {address_with_token_id[0] for address_with_token_id in addresses_with_token_ids}
        base_queryset = Token.objects.filter(
            Q(address__in=addresses_set) | Q(events_bugged=True)
        ).order_by('name')
        if only_trusted:
            addresses = list(base_queryset.erc721().filter(trusted=True).values_list('address', flat=True))
        elif exclude_spam:
            addresses = list(base_queryset.erc721().filter(spam=False).values_list('address', flat=True))
        else:
            # There could be some addresses that are not in the list
            addresses = set()
            for token in base_queryset:
                if token.is_erc721():
                    addresses.add(token.address)
                if token.address in addresses_set:  # events_bugged tokens might not be on the `addresses_set`
                    addresses_set.remove(token.address)
            # Add unknown addresses
            addresses.union(addresses_set)

        return [address_with_token_id for address_with_token_id in addresses_with_token_ids
                if address_with_token_id[0] in addresses]

    def get_collectibles(self, safe_address: str, only_trusted: bool = False,
                         exclude_spam: bool = False) -> List[Collectible]:
        """
        Get collectibles using the owner, addresses and the token_ids
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return:
        """
        unfiltered_addresses_with_token_ids = EthereumEvent.objects.erc721_owned_by(address=safe_address)
        for address, _ in unfiltered_addresses_with_token_ids:
            # Store tokens in database if not present
            self.get_token_info(address)  # This is cached
        addresses_with_token_ids = self._filter_addresses(unfiltered_addresses_with_token_ids,
                                                          only_trusted, exclude_spam)
        if not addresses_with_token_ids:
            return []

        logger.debug('Getting token_uris for %s', addresses_with_token_ids)
        token_uris = self.get_token_uris(addresses_with_token_ids)
        logger.debug('Got token_uris for %s', addresses_with_token_ids)
        collectibles = []
        for (token_address, token_id), token_uri in zip(addresses_with_token_ids, token_uris):
            token_info = self.get_token_info(token_address)
            collectible = self.build_collectible(token_info, token_address, token_id, token_uri)
            collectibles.append(collectible)

        return collectibles

    def get_collectibles_with_metadata(self, safe_address: str, only_trusted: bool = False,
                                       exclude_spam: bool = False) -> List[CollectibleWithMetadata]:
        """
        Get collectibles using the owner, addresses and the token_ids
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return:
        """
        collectibles_with_metadata = []
        for collectible in self.get_collectibles(safe_address, only_trusted=only_trusted, exclude_spam=exclude_spam):
            try:
                metadata = self.get_metadata(collectible)
            except MetadataRetrievalException:
                metadata = {}
                logger.warning(f'Cannot retrieve token-uri={collectible.uri} '
                               f'for token-address={collectible.address}')

            collectibles_with_metadata.append(
                CollectibleWithMetadata(collectible.token_name, collectible.token_symbol, collectible.logo_uri,
                                        collectible.address, collectible.id, collectible.uri, metadata)
            )
        return collectibles_with_metadata

    @cachedmethod(cache=operator.attrgetter('cache_token_info'))
    @cache_memoize(60 * 60 * 24, prefix='collectibles-get_token_info')  # 1 day
    def get_token_info(self, token_address: str) -> Optional[Erc721InfoWithLogo]:
        """
        :param token_address:
        :return: Erc721 name and symbol. If it cannot be found, `name=''` and `symbol=''`
        """
        try:
            token = Token.objects.get(address=token_address)
            return Erc721InfoWithLogo.from_token(token)
        except Token.DoesNotExist:
            if token := Token.objects.create_from_blockchain(token_address):
                return Erc721InfoWithLogo.from_token(token)

    def get_token_uris(self, addresses_with_token_ids: Sequence[Tuple[str, int]]) -> List[Optional[str]]:
        """
        Cache token_uris, as they shouldn't change
        :param addresses_with_token_ids:
        :return: List of token_uris in the same orther that `addresses_with_token_ids` were provided
        """
        not_found = [address_with_token_id for address_with_token_id in addresses_with_token_ids
                     if address_with_token_id not in self.cache_token_uri]
        # Find missing in database
        try:
            self.cache_token_uri.update({address_with_token_id: token_uri
                                        for address_with_token_id, token_uri
                                        in zip(not_found,
                                               self.ethereum_client.erc721.get_token_uris(not_found))})
        except IOError as exc:
            raise NodeConnectionError from exc

        return [self.cache_token_uri[address_with_token_id]
                for address_with_token_id in addresses_with_token_ids]
