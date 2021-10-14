import logging

import requests

from .exceptions import CannotGetPrice

logger = logging.getLogger(__name__)


class KucoinClient:
    PRICE_URL = "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=EWT-USDT"

    def __init__(self):
        self.http_session = requests.Session()

    def get_ewt_usd_price(self) -> float:
        try:
            response = self.http_session.get(self.PRICE_URL, timeout=10)
            result = response.json()
            return float(result["data"]["price"])
        except (ValueError, IOError) as e:
            raise CannotGetPrice from e
