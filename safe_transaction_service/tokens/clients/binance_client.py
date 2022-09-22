import logging

import requests

from .exceptions import CannotGetPrice

logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self):
        self.http_session = requests.Session()

    def _get_price(self, symbol: str) -> float:
        url = f"https://api.binance.com/api/v3/avgPrice?symbol={symbol}"
        try:
            response = self.http_session.get(url, timeout=10)
            api_json = response.json()
            if not response.ok:
                logger.warning("Cannot get price from url=%s", url)
                raise CannotGetPrice(api_json.get("msg"))

            price = float(api_json["price"])
            if not price:
                raise CannotGetPrice(f"Price from url={url} is {price}")
            return price
        except (ValueError, IOError) as e:
            raise CannotGetPrice from e

    def get_ada_usd_price(self) -> float:
        return self._get_price("ADAUSDT")

    def get_aurora_usd_price(self):
        return self._get_price("NEARUSDT")

    def get_bnb_usd_price(self) -> float:
        return self._get_price("BNBUSDT")

    def get_eth_usd_price(self) -> float:
        """
        :return: current USD price for Ethereum
        :raises: CannotGetPrice
        """
        return self._get_price("ETHUSDT")

    def get_matic_usd_price(self) -> float:
        """
        :return: current USD price for MATIC
        :raises: CannotGetPrice
        """
        return self._get_price("MATICUSDT")
