from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

import requests


@dataclass
class SafeRelayToken:
    address: str
    name: str
    symbol: str
    decimals: int


class SafeRelayTokenClient:
    def __init__(self, base_url: str = 'https://safe-relay.gnosis.io/'):
        self.base_url = base_url
        self.headers = {
            'content-type': 'application/json'
        }

    def _do_query(self):
        url = urljoin(self.base_url, 'api/v1/tokens/?limit=1000')
        response = requests.get(url, headers=self.headers)
        if response.ok:
            return response.json().get('results', [])
        else:
            return []

    def get_tokens(self) -> Iterable[SafeRelayToken]:
        return [SafeRelayToken(token['address'], token['name'], token['symbol'], token['decimals'])
                for token in self._do_query()]
