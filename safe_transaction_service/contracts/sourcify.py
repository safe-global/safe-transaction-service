from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from web3 import Web3


@dataclass
class ContractMetadata:
    name: Optional[str]
    abi: List[Dict[str, Any]]


class Sourcify:
    def __init__(self, base_url: str = 'https://contractrepo.komputing.org/'):
        self.base_url = base_url

    def _get_abi_from_metadata(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        return metadata['output']['abi']

    def _get_name_from_metadata(self, metadata: Dict[str, Any]) -> Optional[str]:
        values = list(metadata['settings'].get('compilationTarget', {}).values())
        if values:
            return values[0]

    def _do_request(self, url: str) -> Optional[Dict[str, Any]]:
        response = requests.get(url)
        if not response.ok:
            return None

        return response.json()

    def get_contract_metadata(self, contract_address: str, network_id: int = 1) -> Optional[ContractMetadata]:
        assert Web3.isChecksumAddress(contract_address), 'Expecting a checksummed address'

        url = urljoin(self.base_url, f'/contract/{network_id}/{contract_address}/metadata.json')
        metadata = self._do_request(url)
        if metadata:
            abi = self._get_abi_from_metadata(metadata)
            name = self._get_name_from_metadata(metadata)
            return ContractMetadata(name, abi)
        else:
            return None
