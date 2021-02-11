import logging
from urllib.parse import urljoin

import requests
from eth_typing import ChecksumAddress

logger = logging.getLogger(__name__)


class CoingeckoClient:
    base_url = 'https://api.coingecko.com/'

    def __init__(self):
        self.http_session = requests.session()

    def _get_price(self, url: str, name: str):
        try:
            response = self.http_session.get(url)
            if not response.ok:
                raise IOError
            # Result is returned with lowercased `token_address`
            price = response.json().get(name)
            if price and 'usd' in price:
                return price['usd']
            else:
                return 0.
        except (IOError, ValueError):
            logger.warning('Error getting usd value on coingecko for token-name=%s', name)
            return 0.

    def get_price(self, name: str) -> float:
        """
        :param name: coin name
        :return: usd price for token name, 0. if not found
        """
        name = name.lower()
        url = urljoin(self.base_url,
                      f'/api/v3/simple/price?ids={name}&vs_currencies=usd')
        return self._get_price(url, name)

    def get_token_price(self, token_address: ChecksumAddress) -> float:
        """
        :param token_address:
        :return: usd price for token address, 0. if not found
        """
        token_address = token_address.lower()
        url = urljoin(self.base_url,
                      f'api/v3/simple/token_price/ethereum?contract_addresses={token_address}&vs_currencies=usd')
        return self._get_price(url, token_address)
