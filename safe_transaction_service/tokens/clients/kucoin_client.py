import logging

import requests

from .exceptions import CannotGetPrice

logger = logging.getLogger(__name__)


class KucoinClient:
    def __init__(self):
        self.http_session = requests.session()

    def get_ewt_usd_price(self) -> float:
        url = 'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=EWT-USDT'
        response = self.http_session.get(url)
        try:
            result = response.json()
            return float(result['data']['price'])
        except (ValueError, IOError) as e:
            raise CannotGetPrice from e
