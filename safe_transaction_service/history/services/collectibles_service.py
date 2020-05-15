import logging
import operator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from cachetools import TTLCache, cachedmethod
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.contracts import get_erc721_contract

from ..models import EthereumEvent

logger = logging.getLogger(__name__)


class CollectiblesServiceException(Exception):
    pass


@dataclass
class Collectible:
    address: str
    id: str
    uri: str


@dataclass
class CollectibleWithMetadata(Collectible):
    metadata: Dict[str, Any]


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
            try:
                balance = erc_721_contract.functions.balanceOf('0x1ca57CBf18Ab08119ACb4CA2517650fFc3BA6D40').call()
                for i in range(balance):
                    id = erc_721_contract.functions.tokenOfOwnerByIndex(safe_address, 0).call()
                    uri = erc_721_contract.functions.tokenURI(id).call()
                    collectibles.append(Collectible(erc721_address, id, uri))
            except ValueError:
                logger.warning('Cannot get ERC721 info token=%s with owner=%s',
                               erc721_address, safe_address, exc_info=True)
        return collectibles

    def get_collectibles_with_metadata(self, safe_address: str):
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
                CollectibleWithMetadata(collectible.address, collectible.id, collectible.uri, metadata)
            )

        return collectibles_with_metadata
