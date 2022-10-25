import logging

import requests

from .exceptions import CannotGetPrice

logger = logging.getLogger(__name__)


class KucoinClient:
    def __init__(self):
        self.http_session = requests.Session()

    def _get_price(self, symbol: str):
        url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol}"

        try:
            response = self.http_session.get(url, timeout=10)
            result = response.json()
            return float(result["data"]["price"])
        except (ValueError, IOError) as e:
            logger.warning("Cannot get price from url=%s", url)
            raise CannotGetPrice from e

    def get_ewt_usd_price(self) -> float:
        """
        :return: current USD price for Energy Web Token
        :raises: CannotGetPrice
        """
        return self._get_price("EWT-USDT")

    def get_cro_usd_price(self) -> float:
        """
        :return: current USD price for Cronos
        :raises: CannotGetPrice
        """
        return self._get_price("CRO-USDT")

    def get_kcs_usd_price(self) -> float:
        """
        :return: current USD price for KuCoin Token
        :raises: CannotGetPrice
        """
        return self._get_price("KCS-USDT")
