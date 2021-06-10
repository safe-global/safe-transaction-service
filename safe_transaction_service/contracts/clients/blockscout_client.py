import json
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from eth_typing import ChecksumAddress

from gnosis.eth.clients.sourcify import ContractMetadata
from gnosis.eth.ethereum_client import EthereumNetwork


class BlockscoutClientException(Exception):
    pass


class BlockScoutConfigurationProblem(BlockscoutClientException):
    pass


class BlockscoutClient:
    NETWORK_WITH_URL = {
        EthereumNetwork.XDAI: 'https://blockscout.com/poa/xdai/',
        EthereumNetwork.MATIC: 'https://polygon-explorer-mainnet.chainstacklabs.com/',
        EthereumNetwork.MUMBAI: 'https://polygon-explorer-mumbai.chainstacklabs.com/',
        EthereumNetwork.ENERGY_WEB_CHAIN: 'https://explorer.energyweb.org/',
        EthereumNetwork.VOLTA: 'https://volta-explorer.energyweb.org/',
    }

    def __init__(self, network: EthereumNetwork):
        self.network = network
        self.base_url = self.NETWORK_WITH_URL.get(network)
        if self.base_url is None:
            raise BlockScoutConfigurationProblem(f'Network {network.name} - {network.value} not supported')
        self.grahpql_url = self.base_url + '/graphiql'
        self.http_session = requests.Session()

    def build_url(self, path: str):
        return urljoin(self.base_url, path)

    def _do_request(self, url: str, query: str) -> Optional[Dict[str, Any]]:
        response = self.http_session.post(url, json={'query': query}, timeout=10)
        if not response.ok:
            return None

        return response.json()

    def get_contract_metadata(self, address: ChecksumAddress) -> Optional[ContractMetadata]:
        query = '{address(hash: "%s") { hash, smartContract {name, abi} }}' % address
        result = self._do_request(self.grahpql_url, query)
        if result and 'error' not in result and result.get('data', {}).get('address', {}) \
                and result['data']['address']['smartContract']:
            smart_contract = result['data']['address']['smartContract']
            return ContractMetadata(smart_contract['name'], json.loads(smart_contract['abi']), False)
