import logging
from functools import lru_cache
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from eth_typing import ChecksumAddress

from gnosis.eth import EthereumNetwork

from safe_transaction_service.tokens.clients.base_client import BaseHTTPClient
from safe_transaction_service.tokens.clients.exceptions import (
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
        EthereumNetwork.METER_MAINNET: "meter",
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
