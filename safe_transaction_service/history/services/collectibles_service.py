import logging
import operator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin

from django.conf import settings
from django.core.cache import cache as django_cache

import gevent
import requests
from cache_memoize import cache_memoize
from cachetools import TTLCache, cachedmethod
from eth_typing import ChecksumAddress
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_transaction_service.tokens.constants import (
    CRYPTO_KITTIES_CONTRACT_ADDRESSES,
    ENS_CONTRACTS_WITH_TLD,
)
from safe_transaction_service.tokens.models import Token
from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.utils import chunks

from ..clients import EnsClient
from ..exceptions import NodeConnectionException
from ..models import ERC721Transfer

logger = logging.getLogger(__name__)


class CollectiblesServiceException(Exception):
    pass


class MetadataRetrievalException(CollectiblesServiceException):
    pass


def ipfs_to_http(uri: Optional[str]) -> Optional[str]:
    if uri and uri.startswith("ipfs://"):
        uri = uri.replace("ipfs://ipfs/", "ipfs://")
        return urljoin(
            settings.IPFS_GATEWAY, uri.replace("ipfs://", "", 1)
        )  # Use ipfs gateway
    return uri


@dataclass
class Erc721InfoWithLogo:
    """
    ERC721 info from Blockchain
    """

    address: str
    name: str
    symbol: str
    logo_uri: str

    @classmethod
    def from_token(cls, token: Token):
        return cls(
            token.address,
            token.name,
            token.symbol,
            token.get_full_logo_uri(),
        )


@dataclass
class Collectible:
    """
    Collectible built from ERC721InfoWithLogo
    """

    token_name: str
    token_symbol: str
    logo_uri: str
    address: str
    id: int
    uri: str


@dataclass
class CollectibleWithMetadata(Collectible):
    """
    Collectible with metadata parsed if possible
    """

    metadata: Dict[str, Any]
    name: Optional[str] = field(init=False)
    description: Optional[str] = field(init=False)
    image_uri: Optional[str] = field(init=False)

    def get_name(self) -> Optional[str]:
        if self.metadata:
            for key in ("name",):
                if key in self.metadata:
                    return self.metadata[key]

    def get_description(self) -> Optional[str]:
        if self.metadata:
            for key in ("description",):
                if key in self.metadata:
                    return self.metadata[key]

    def get_metadata_image(self) -> Optional[str]:
        if not self.metadata:
            return None

        for key in ("image", "image_url", "image_uri", "imageUri", "imageUrl"):
            if key in self.metadata:
                return self.metadata[key]

        for key, value in self.metadata.items():
            if (
                key.lower().startswith("image")
                and isinstance(value, str)
                and value.startswith("http")
            ):
                return value

    def __post_init__(self):
        self.name = self.get_name()
        self.description = self.get_description()
        self.image_uri = ipfs_to_http(self.get_metadata_image())


class CollectiblesServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = CollectiblesService(EthereumClientProvider(), get_redis())

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class CollectiblesService:
    ENS_IMAGE_URL = "https://gnosis-safe-token-logos.s3.amazonaws.com/ENS.png"
    METADATA_MAX_CONTENT_LENGTH = int(
        0.2 * 1024 * 1024
    )  # 0.2Mb is the maximum metadata size allowed

    def __init__(self, ethereum_client: EthereumClient, redis: Redis):
        self.ethereum_client = ethereum_client
        self.ethereum_network = ethereum_client.get_network()
        self.redis = redis
        self.ens_service: EnsClient = EnsClient(self.ethereum_network.value)

        self.cache_uri_metadata = TTLCache[str, Optional[Dict[str, Any]]](
            maxsize=4096, ttl=60 * 60 * 24
        )  # 1 day of caching
        self.cache_token_info: TTLCache[ChecksumAddress, Erc721InfoWithLogo] = TTLCache(
            maxsize=4096, ttl=60 * 30
        )  # 2 hours of caching

    @cachedmethod(cache=operator.attrgetter("cache_uri_metadata"))
    @cache_memoize(
        60 * 60 * 24,
        prefix="collectibles-_retrieve_metadata_from_uri",
        cache_exceptions=(MetadataRetrievalException,),
    )  # 1 day
    def _retrieve_metadata_from_uri(self, uri: str) -> Any:
        """
        Get metadata from URI. Currently just ipfs/http/https is supported

        :param uri: Metadata URI, like http://example.org/token/3 or ipfs://<keccak256>
        :return: Metadata as a decoded json
        """
        uri = ipfs_to_http(uri)

        if not uri or not uri.startswith("http"):
            raise MetadataRetrievalException(uri)

        try:
            logger.debug("Getting metadata for uri=%s", uri)
            with requests.get(uri, timeout=15, stream=True) as response:
                if not response.ok:
                    logger.debug("Cannot get metadata for uri=%s", uri)
                    raise MetadataRetrievalException(uri)

                content_length = response.headers.get("content-length", 0)
                content_type = response.headers.get("content-type", "")
                if int(content_length) > self.METADATA_MAX_CONTENT_LENGTH:
                    raise MetadataRetrievalException(
                        f"Content-length={content_length} for uri={uri} is too big"
                    )

                if "application/json" not in content_type:
                    raise MetadataRetrievalException(
                        f"Content-type={content_type} for uri={uri} is not valid, "
                        f'expected "application/json"'
                    )

                logger.debug("Got metadata for uri=%s", uri)

                # Some requests don't provide `Content-Length` on the headers
                if len(response.content) > self.METADATA_MAX_CONTENT_LENGTH:
                    raise MetadataRetrievalException(
                        f"Retrieved content for uri={uri} is too big"
                    )

                return response.json()
        except (IOError, ValueError) as e:
            raise MetadataRetrievalException(uri) from e

    def build_collectible(
        self,
        token_info: Optional[Erc721InfoWithLogo],
        token_address: ChecksumAddress,
        token_id: int,
        token_metadata_uri: Optional[str],
    ) -> Collectible:
        if not token_metadata_uri:
            if token_address in CRYPTO_KITTIES_CONTRACT_ADDRESSES:
                token_metadata_uri = f"https://api.cryptokitties.co/kitties/{token_id}"
            else:
                logger.info(
                    "Not available token_uri to retrieve metadata for ERC721 token=%s with token-id=%d",
                    token_address,
                    token_id,
                )
        name = token_info.name if token_info else ""
        symbol = token_info.symbol if token_info else ""
        logo_uri = token_info.logo_uri if token_info else ""
        return Collectible(
            name, symbol, logo_uri, token_address, token_id, token_metadata_uri
        )

    def get_metadata(self, collectible: Collectible) -> Any:
        if tld := ENS_CONTRACTS_WITH_TLD.get(
            collectible.address
        ):  # Special case for ENS
            label_name = self.ens_service.query_by_domain_hash(collectible.id)
            return {
                "name": f"{label_name}.{tld}" if label_name else f".{tld}",
                "description": ("" if label_name else "Unknown ")
                + f".{tld} ENS Domain",
                "image": self.ENS_IMAGE_URL,
            }

        return self._retrieve_metadata_from_uri(collectible.uri)

    def get_collectibles(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[Collectible], int]:
        """
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :param limit: page size
        :param offset: page position
        :return: Collectibles (using the owner, addresses and the token_ids) and count (total of collectibles)
        """

        # Cache based on the number of erc721 events
        number_erc721_events = ERC721Transfer.objects.to_or_from(safe_address).count()

        if number_erc721_events == 0:
            # No need for further DB/Cache calls
            return [], 0

        cache_key = f"collectibles:{safe_address}:{only_trusted}:{exclude_spam}:{limit}{offset}:{number_erc721_events}"
        cache_key_count = (
            f"collectibles_count:{safe_address}:{only_trusted}:{exclude_spam}"
        )
        if collectibles := django_cache.get(cache_key):
            count = django_cache.get(cache_key_count)
            return collectibles, count
        else:
            collectibles, count = self._get_collectibles(
                safe_address,
                only_trusted,
                exclude_spam,
                limit=limit,
                offset=offset,
            )
            django_cache.set(cache_key, collectibles, 60 * 10)  # 10 minutes cache
            django_cache.set(cache_key_count, count, 60 * 10)  # 10 minutes cache
            return collectibles, count

    def _get_collectibles(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[Collectible], int]:
        """
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :param limit: page size
        :param offset: page position
        :return: Collectibles (using the owner, addresses and the token_ids) and count (total of collectibles)
        """
        addresses_with_token_ids = ERC721Transfer.objects.erc721_owned_by(
            safe_address, only_trusted=only_trusted, exclude_spam=exclude_spam
        )
        if not addresses_with_token_ids:
            return [], 0

        count = len(addresses_with_token_ids)
        # TODO Paginate on DB
        if limit is not None:
            addresses_with_token_ids = addresses_with_token_ids[offset : offset + limit]

        for address, _ in addresses_with_token_ids:
            # Store tokens in database if not present
            self.get_token_info(address)  # This is cached

        logger.debug("Getting token_uris for %s", addresses_with_token_ids)
        # Chunk token uris to prevent stressing the node
        token_uris = []

        for addresses_with_token_ids_chunk in chunks(addresses_with_token_ids, 25):
            token_uris.extend(self.get_token_uris(addresses_with_token_ids_chunk))
        logger.debug("Got token_uris for %s", addresses_with_token_ids)
        collectibles = []
        for (token_address, token_id), token_uri in zip(
            addresses_with_token_ids, token_uris
        ):
            token_info = self.get_token_info(token_address)
            collectible = self.build_collectible(
                token_info, token_address, token_id, token_uri
            )
            collectibles.append(collectible)

        return collectibles, count

    def _get_collectibles_with_metadata(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Tuple[List[CollectibleWithMetadata], int]:
        """
        Get collectibles using the owner, addresses and the token_ids

        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :param limit: page size
        :param offset: page position
        :return: collectibles and count
        """
        collectibles_with_metadata: List[CollectibleWithMetadata] = []
        collectibles, count = self.get_collectibles(
            safe_address,
            only_trusted=only_trusted,
            exclude_spam=exclude_spam,
            limit=limit,
            offset=offset,
        )
        jobs = [
            gevent.spawn(self.get_metadata, collectible) for collectible in collectibles
        ]
        _ = gevent.joinall(jobs)
        for collectible, job in zip(collectibles, jobs):
            try:
                metadata = job.get()
                if not isinstance(metadata, dict):
                    metadata = {}
                    logger.warning(
                        "A dictionary metadata was expected on token-uri=%s for token-address=%s",
                        collectible.uri,
                        collectible.address,
                    )
            except MetadataRetrievalException:
                metadata = {}
                logger.warning(
                    "Cannot retrieve metadata on token-uri=%s for token-address=%s",
                    collectible.uri,
                    collectible.address,
                )

            collectibles_with_metadata.append(
                CollectibleWithMetadata(
                    collectible.token_name,
                    collectible.token_symbol,
                    collectible.logo_uri,
                    collectible.address,
                    collectible.id,
                    collectible.uri,
                    metadata,
                )
            )
        return collectibles_with_metadata, count

    def get_collectibles_with_metadata(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
    ) -> List[CollectibleWithMetadata]:
        """
         Get collectibles v1 returns no paginated response
        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :return: collectibles
        """
        collectibles, _ = self._get_collectibles_with_metadata(
            safe_address, only_trusted, exclude_spam
        )
        return collectibles

    def get_collectibles_with_metadata_paginated(
        self,
        safe_address: ChecksumAddress,
        only_trusted: bool = False,
        exclude_spam: bool = False,
        limit: int = 10,
        offset: int = 0,
    ) -> Tuple[List[CollectibleWithMetadata], int]:
        """
        Get collectibles paginated

        :param safe_address:
        :param only_trusted: If True, return balance only for trusted tokens
        :param exclude_spam: If True, exclude spam tokens
        :param limit: page size
        :param offset: page position
        :return: collectibles and count
        """
        return self._get_collectibles_with_metadata(
            safe_address, only_trusted, exclude_spam, limit, offset
        )

    @cachedmethod(cache=operator.attrgetter("cache_token_info"))
    @cache_memoize(60 * 60, prefix="collectibles-get_token_info")  # 1 hour
    def get_token_info(
        self, token_address: ChecksumAddress
    ) -> Optional[Erc721InfoWithLogo]:
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

    def get_token_uris(
        self, addresses_with_token_ids: Sequence[Tuple[ChecksumAddress, int]]
    ) -> List[Optional[str]]:
        """
        Cache token_uris, as they shouldn't change

        :param addresses_with_token_ids:
        :return: List of token_uris in the same other that `addresses_with_token_ids` were provided
        """

        def get_redis_key(address_with_token_id: Tuple[ChecksumAddress, int]) -> str:
            token_address, token_id = address_with_token_id
            return f"token-uri:{token_address}:{token_id}"

        # Try finding missing token uris in redis
        redis_token_uris = self.redis.mget(
            get_redis_key(address_with_token_id)
            for address_with_token_id in addresses_with_token_ids
        )
        # Redis does not allow `None`, so empty string is used for uris searched but not found
        found_uris: Dict[Tuple[ChecksumAddress, int], Optional[str]] = {}
        not_found_uris: List[Tuple[ChecksumAddress, int]] = []

        for address_with_token_id, token_uri in zip(
            addresses_with_token_ids, redis_token_uris
        ):
            if token_uri is None:
                not_found_uris.append(address_with_token_id)
            else:
                found_uris[address_with_token_id] = (
                    token_uri.decode() if token_uri else None
                )

        try:
            # Find missing token uris in blockchain
            logger.debug(
                "Getting token uris from blockchain for %d addresses with tokenIds",
                len(not_found_uris),
            )
            blockchain_token_uris = {
                address_with_token_id: token_uri if token_uri else None
                for address_with_token_id, token_uri in zip(
                    not_found_uris,
                    self.ethereum_client.erc721.get_token_uris(not_found_uris),
                )
            }
            logger.debug("Got token uris from blockchain")
        except (IOError, ValueError):
            logger.warning(
                "Problem when getting token uris from blockchain, trying individually",
                exc_info=True,
            )
            blockchain_token_uris = {}
            for not_found_uri in not_found_uris:
                try:
                    token_uri = self.ethereum_client.erc721.get_token_uris(
                        [not_found_uri]
                    )[0]
                    blockchain_token_uris[not_found_uri] = (
                        token_uri if token_uri else None
                    )
                except ValueError:
                    blockchain_token_uris[not_found_uri] = None
                    logger.warning(
                        "ValueError when getting token uri from blockchain for token and tokenId %s",
                        not_found_uri,
                        exc_info=True,
                    )
                except IOError as exc:
                    raise NodeConnectionException from exc

        if blockchain_token_uris:
            pipe = self.redis.pipeline()
            redis_map_to_store = {
                get_redis_key(address_with_token_id): token_uri
                if token_uri is not None
                else ""
                for address_with_token_id, token_uri in blockchain_token_uris.items()
            }
            pipe.mset(redis_map_to_store)
            for key in redis_map_to_store.keys():
                pipe.expire(key, 60 * 60 * 24)  # 1 day of caching
            pipe.execute()
            found_uris.update(blockchain_token_uris)

        return [
            found_uris[address_with_token_id]
            for address_with_token_id in addresses_with_token_ids
        ]
