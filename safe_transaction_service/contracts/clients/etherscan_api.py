import json
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

from gnosis.eth.ethereum_client import EthereumNetwork


class EtherscanApiConfigurationError(Exception):
    pass


class RateLimitError(Exception):
    pass


class EtherscanApi:
    def __init__(self, network: EthereumNetwork, api_key: Optional[str] = None):
        self.network = network
        self.api_key = api_key
        self.base_url = self.get_base_url(network)
        if self.base_url is None:
            raise EtherscanApiConfigurationError(f'Network {network.name} - {network.value} not supported')
        self.http_session = requests.session()

    def build_url(self, path: str):
        url = urljoin(self.base_url, path)
        if self.api_key:
            url += f'&apikey={self.api_key}'
        return url

    def get_base_url(self, network: EthereumNetwork):
        if network == EthereumNetwork.MAINNET:
            return 'https://api.etherscan.io'
        elif network == EthereumNetwork.RINKEBY:
            return 'https://api-rinkeby.etherscan.io'
        elif network == EthereumNetwork.XDAI:
            return 'https://blockscout.com/poa/xdai'
        elif network == EthereumNetwork.ENERGY_WEB_CHAIN:
            return 'https://explorer.energyweb.org'
        elif network == EthereumNetwork.VOLTA:
            return 'https://volta-explorer.energyweb.org'

    def _get_contract_abi(self, contract_address: str) -> Optional[Dict[str, Any]]:
        url = self.build_url(f'api?module=contract&action=getabi&address={contract_address}')
        response = self.http_session.get(url)

        if response.ok:
            response_json = response.json()
            result = response_json['result']
            if 'Max rate limit reached, please use API Key for higher rate limit' == result:
                raise RateLimitError
            if response_json['status'] == '1':
                return json.loads(result)

    def get_contract_abi(self, contract_address: str, retry: bool = True):
        for _ in range(3):
            try:
                return self._get_contract_abi(contract_address)
            except RateLimitError as exc:
                if not retry:
                    raise exc
                else:
                    time.sleep(5)
