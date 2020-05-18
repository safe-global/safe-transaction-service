import logging
import operator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from cachetools import cachedmethod
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import get_erc721_contract

from ..models import EthereumEvent

logger = logging.getLogger(__name__)


class CollectiblesServiceException(Exception):
    pass


@dataclass
class Collectible:
    name: str
    symbol: str
    address: str
    id: str
    uri: str


@dataclass
class CollectibleWithMetadata(Collectible):
    metadata: Dict[str, Any]
    image_uri: Optional[str] = field(init=False)

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
        self.image_uri = self.get_metadata_image()


class CollectiblesServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = CollectiblesService(EthereumClientProvider())

        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class CollectiblesService:
    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        self.cache_token_info = {}

    def get_collectibles(self, safe_address: str) -> List[Collectible]:
        """
        :param safe_address:
        :return:
        """
        assert Web3.isChecksumAddress(safe_address), f'Not valid address {safe_address} for getting collectibles'

        erc721_addresses = list(EthereumEvent.objects.erc721_tokens_used_by_address(safe_address))
        collectibles = []
        for erc721_address in erc721_addresses:
            erc_721_contract = get_erc721_contract(self.ethereum_client.w3, erc721_address)
            token_info = self.get_token_info(erc721_address)
            if token_info:  # Swap name and symbol if symbol is bigger
                name, symbol = token_info
                if (len(name) - len(symbol)) < -5:  # If symbol is bigger than name, swap them (e.g. POAP)
                    name, symbol = symbol, name
            else:
                name, symbol = ('', '')
            try:
                balance = erc_721_contract.functions.balanceOf(safe_address).call()
                for i in range(balance):
                    token_id = erc_721_contract.functions.tokenOfOwnerByIndex(safe_address, i).call()
                    uri = erc_721_contract.functions.tokenURI(token_id).call()
                    collectibles.append(Collectible(name, symbol, erc721_address, token_id, uri))
            except ValueError:
                logger.warning('Cannot get ERC721 info token=%s with owner=%s',
                               erc721_address, safe_address, exc_info=True)
        return collectibles

    def get_collectibles_with_metadata(self, safe_address: str) -> List[CollectibleWithMetadata]:
        collectibles_with_metadata = []
        for collectible in self.get_collectibles(safe_address):
            response = requests.get(collectible.uri)
            if not response.ok:
                logger.warning(f'Cannot retrieve token-uri={collectible.uri} '
                               f'for token-address={collectible.address}')
                metadata = {}
            else:
                metadata = response.json()
            collectibles_with_metadata.append(
                CollectibleWithMetadata(collectible.name, collectible.symbol,
                                        collectible.address, collectible.id, collectible.uri, metadata)
            )

        return collectibles_with_metadata

    @cachedmethod(cache=operator.attrgetter('cache_token_info'))
    def get_token_info(self, token_address: str):
        try:
            erc_721_contract = get_erc721_contract(self.ethereum_client.w3, token_address)
            name = erc_721_contract.functions.name().call()
            symbol = erc_721_contract.functions.symbol().call()
            return name, symbol
        except ValueError:
            logger.warning('Cannot get erc721 token info for token-address=%s', token_address)
            return None
