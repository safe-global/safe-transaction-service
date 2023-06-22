import logging
from functools import lru_cache
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from eth_typing import ChecksumAddress

from gnosis.eth import EthereumNetwork

from safe_transaction_service.tokens.clients.base_client import BaseHTTPClient
from safe_transaction_service.tokens.clients.exceptions import (
    CannotGetPrice,
    Coingecko404,
    CoingeckoRateLimitError,
    CoingeckoRequestError,
)

logger = logging.getLogger(__name__)


class CoingeckoClient(BaseHTTPClient):
    ASSET_BY_NETWORK = {
        EthereumNetwork.ARBITRUM_ONE: "arbitrum-one",
        EthereumNetwork.AURORA_MAINNET: "aurora",
        EthereumNetwork.AVALANCHE_C_CHAIN: "avalanche",
        EthereumNetwork.BINANCE_SMART_CHAIN_MAINNET: "binance-smart-chain",
        EthereumNetwork.FUSE_MAINNET: "fuse",
        EthereumNetwork.GNOSIS: "xdai",
        EthereumNetwork.KCC_MAINNET: "kucoin-community-chain",
        EthereumNetwork.MAINNET: "ethereum",
        EthereumNetwork.METIS_ANDROMEDA_MAINNET: "metis-andromeda",
        EthereumNetwork.OPTIMISM: "optimistic-ethereum",
        EthereumNetwork.POLYGON: "polygon-pos",
        EthereumNetwork.POLYGON_ZKEVM: "polygon-zkevm",
        EthereumNetwork.CELO_MAINNET: "celo",
    }
    base_url = "https://api.coingecko.com/"

    def __init__(
        self, network: Optional[EthereumNetwork] = None, request_timeout: int = 10
    ):
        super().__init__(request_timeout=request_timeout)
        self.asset_platform = self.ASSET_BY_NETWORK.get(network, "ethereum")

    @classmethod
    def supports_network(cls, network: EthereumNetwork):
        return network in cls.ASSET_BY_NETWORK

    def _do_request(self, url: str) -> Dict[str, Any]:
        try:
            response = self.http_session.get(url, timeout=self.request_timeout)
            if not response.ok:
                if response.status_code == 404:
                    raise Coingecko404(url)
                if response.status_code == 429:
                    raise CoingeckoRateLimitError(url)
                raise CoingeckoRequestError(url)
            return response.json()
        except (ValueError, IOError) as e:
            logger.warning("Problem fetching %s", url)
            raise CoingeckoRequestError from e

    def _get_price(self, url: str, name: str):
        try:
            result = self._do_request(url)

            # Result is returned with lowercased `name` (if querying by contract address, then `token_address`)
            price = result.get(name)
            if price and price.get("usd"):
                return price["usd"]
            else:
                raise CannotGetPrice(f"Price from url={url} is {price}")
        except CoingeckoRequestError as e:
            raise CannotGetPrice(
                f"Cannot get price from Coingecko for token={name}"
            ) from e

    def get_price(self, name: str) -> float:
        """
        :param name: coin name
        :return: usd price for token name, 0. if not found
        """
        name = name.lower()
        url = urljoin(
            self.base_url, f"/api/v3/simple/price?ids={name}&vs_currencies=usd"
        )
        return self._get_price(url, name)

    def get_token_price(self, token_address: ChecksumAddress) -> float:
        """
        :param token_address:
        :return: usd price for token address, 0. if not found
        """
        token_address = token_address.lower()
        url = urljoin(
            self.base_url,
            f"api/v3/simple/token_price/{self.asset_platform}?contract_addresses={token_address}&vs_currencies=usd",
        )
        return self._get_price(url, token_address)

    @lru_cache(maxsize=128)
    def get_token_info(
        self, token_address: ChecksumAddress
    ) -> Optional[Dict[str, Any]]:
        token_address = token_address.lower()
        url = urljoin(
            self.base_url,
            f"api/v3/coins/{self.asset_platform}/contract/{token_address}",
        )
        try:
            return self._do_request(url)
        except Coingecko404:
            return None

    def get_token_logo_url(self, token_address: ChecksumAddress) -> Optional[str]:
        token_info = self.get_token_info(token_address)
        if token_info:
            return token_info["image"]["large"]

    def get_ada_usd_price(self) -> float:
        return self.get_price("cardano")

    def get_avax_usd_price(self) -> float:
        return self.get_price("avalanche-2")

    def get_aoa_usd_price(self) -> float:
        return self.get_price("aurora")

    def get_bnb_usd_price(self) -> float:
        return self.get_price("binancecoin")

    def get_ewt_usd_price(self) -> float:
        return self.get_price("energy-web-token")

    def get_matic_usd_price(self) -> float:
        return self.get_price("matic-network")

    def get_gather_usd_price(self) -> float:
        return self.get_price("gather")

    def get_fuse_usd_price(self) -> float:
        return self.get_price("fuse-network-token")

    def get_kcs_usd_price(self) -> float:
        return self.get_price("kucoin-shares")

    def get_metis_usd_price(self) -> float:
        return self.get_price("metis-token")
