import logging
import operator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests
from cachetools import cachedmethod

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import get_erc721_contract
from gnosis.eth.ethereum_client import Erc721Info, InvalidERC721Info

from ..clients import EnsClient
from ..models import EthereumEvent

logger = logging.getLogger(__name__)


class CollectiblesServiceException(Exception):
    pass


class MetadataRetrievalException(CollectiblesServiceException):
    pass


@dataclass
class Collectible:
    token_name: str
    token_symbol: str
    address: str
    id: str
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
    CRYPTO_KITTIES_CONTRACT_ADDRESSES = {
        '0x06012c8cf97BEaD5deAe237070F9587f8E7A266d',  # Mainnet
        '0x16baF0dE678E52367adC69fD067E5eDd1D33e3bF'  # Rinkeby
    }
    ENS_CONTRACTS_WITH_TLD = {
        '0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85': 'eth',  # ENS .eth registrar (Every network)
    }
    ENS_IMAGE_URL = 'https://gnosis-safe-token-logos.s3.amazonaws.com/ENS.png'

    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        self.cache_token_info: Dict[str, Tuple[str, str]] = {}
        self.ens_service: EnsClient = EnsClient(ethereum_client.get_network().value)

    @lru_cache
    def _retrieve_metadata_from_uri(self, uri: str) -> Dict[Any, Any]:
        """
        Get metadata from uri. Maybe at some point support IPFS or another protocols. Currently just http/https is
        supported
        :param uri: Uri starting with the protocol, like http://example.org/token/3
        :return: Metadata as a decoded json
        """
        if not uri or not uri.startswith('http'):
            raise MetadataRetrievalException(uri)

        try:
            logger.debug('Getting metadata for uri=%s', uri)
            response = requests.get(uri)
            if not response.ok:
                logger.debug('Error getting metadata for uri=%s', uri)
                raise MetadataRetrievalException(uri)
            else:
                logger.debug('Got metadata for uri=%s', uri)
                return response.json()
        except requests.RequestException as e:
            raise MetadataRetrievalException(uri) from e

    def build_collectible(self, token_info: Erc721Info, token_address: str, token_id: int,
                          token_uri: Optional[str]) -> Collectible:
        if not token_uri:
            if token_address in self.CRYPTO_KITTIES_CONTRACT_ADDRESSES:
                token_uri = f'https://api.cryptokitties.co/kitties/{token_id}'
            else:
                logger.warning('Not available token_uri to retrieve metadata for ERC721 token=%s with token-id=%d',
                               token_address, token_id, exc_info=True)
        return Collectible(token_info.name, token_info.symbol, token_address, token_id, token_uri)

    def get_metadata(self, collectible: Collectible) -> Dict[Any, Any]:
        tld = self.ENS_CONTRACTS_WITH_TLD.get(collectible.address)
        if tld:  # Special case for ENS
            label_name = self.ens_service.query_by_domain_hash(collectible.id)
            return {
                'name': f'{label_name}.{tld}' if label_name else f'.{tld}',
                'description': ('' if label_name else 'Unknown ') + f'.{tld} ENS Domain',
                'image': self.ENS_IMAGE_URL,
            }

        return self._retrieve_metadata_from_uri(collectible.uri)

    def get_collectibles(self, safe_address: str) -> List[Collectible]:
        """
        Get collectibles using the owner, addresses and the token_ids
        :param safe_address:
        :return:
        """
        addresses_with_token_ids = EthereumEvent.objects.erc721_owned_by(address=safe_address)

        logger.debug('Getting token_uris for %s', addresses_with_token_ids)
        token_uris = self.ethereum_client.erc721.get_token_uris(addresses_with_token_ids)
        logger.debug('Got token_uris for %s', addresses_with_token_ids)
        collectibles = []
        for (token_address, token_id), token_uri in zip(addresses_with_token_ids, token_uris):
            token_info = self.get_token_info(token_address)
            collectible = self.build_collectible(token_info, token_address, token_id, token_uri)
            collectibles.append(collectible)

        return collectibles

    def get_collectibles_with_metadata(self, safe_address: str) -> List[CollectibleWithMetadata]:
        collectibles_with_metadata = []
        for collectible in self.get_collectibles(safe_address):
            try:
                metadata = self.get_metadata(collectible)
            except MetadataRetrievalException:
                metadata = {}
                logger.warning(f'Cannot retrieve token-uri={collectible.uri} '
                               f'for token-address={collectible.address}')

            collectibles_with_metadata.append(
                CollectibleWithMetadata(collectible.token_name, collectible.token_symbol,
                                        collectible.address, collectible.id, collectible.uri, metadata)
            )
        return collectibles_with_metadata

    def get_token_info(self, token_address: str) -> Erc721Info:
        """
        :param token_address:
        :return: Erc721 name and symbol. If it cannot be found, `name=''` and `symbol=''`
        """
        if token_address in self.ENS_CONTRACTS_WITH_TLD:
            token_info = Erc721Info('Ethereum Name Service', 'ENS')
        else:
            token_info = self.retrieve_token_info(token_address)

        # If symbol is way bigger than name, swap them (e.g. POAP)
        if token_info and (len(token_info.name) - len(token_info.symbol)) < -5:
            token_info = Erc721Info(token_info.symbol, token_info.name)
        elif not token_info:
            token_info = Erc721Info('', '')

        return token_info

    @cachedmethod(cache=operator.attrgetter('cache_token_info'))
    def retrieve_token_info(self, token_address: str) -> Optional[Erc721Info]:
        """
        Queries blockchain for the token name and symbol
        :param token_address: address for a erc721 token
        :return: tuple with name and symbol of the erc721 token
        """
        try:
            logger.debug('Querying blockchain for info for token=%s', token_address)
            return self.ethereum_client.erc721.get_info(token_address)
        except InvalidERC721Info:
            logger.warning('Cannot get erc721 token info for token-address=%s', token_address)
