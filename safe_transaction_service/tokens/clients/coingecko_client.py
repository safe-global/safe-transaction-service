import logging
from urllib.parse import urljoin

import requests
from eth_typing import ChecksumAddress

from safe_transaction_service.tokens.clients.exceptions import CannotGetPrice

logger = logging.getLogger(__name__)


class CoingeckoClient:
    base_url = 'https://api.coingecko.com/'

    def __init__(self):
        self.http_session = requests.session()

    def _get_price(self, url: str, name: str):
        try:
            response = self.http_session.get(url)
            if not response.ok:
                raise CannotGetPrice
            # Result is returned with lowercased `token_address`
            price = response.json().get(name)
            if price and price.get('usd'):
                return price['usd']
            else:
                raise CannotGetPrice(f'Price from url={url} is {price}')
        except (ValueError, IOError) as e:
            logger.warning('Problem getting usd value on coingecko for token-name=%s', name)
            raise CannotGetPrice from e

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

    def get_ewt_usd_price(self) -> float:
        return self.get_price('energy-web-token')
