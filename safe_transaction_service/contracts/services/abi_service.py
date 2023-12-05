import logging
from functools import cache
from typing import Optional

from django.conf import settings

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.clients import (
    BlockscoutClient,
    BlockScoutConfigurationProblem,
    EtherscanClient,
    EtherscanClientConfigurationProblem,
    SourcifyClient,
    SourcifyClientConfigurationProblem,
)

logger = logging.getLogger(__name__)


@cache
def get_abi_service():
    return AbiService(EthereumClientProvider(), settings.ETHERSCAN_API_KEY)


class AbiService:
    def __init__(
        self, ethereum_client: EthereumClient, etherscan_api_key: Optional[str] = None
    ):
        self.ethereum_client = ethereum_client
        self.ethereum_network = ethereum_client.get_network()
        self.etherscan_api_key = etherscan_api_key
        self.etherscan_client = self.get_etherscan_client()
        self.blockscout_client = self.get_blockscout_client()
        self.sourcify_client = self.get_sourcify_client()

    def get_etherscan_client(self) -> Optional[EthereumClient]:
        try:
            return EtherscanClient(
                self.ethereum_network, api_key=self.etherscan_api_key
            )
        except EtherscanClientConfigurationProblem:
            logger.info(
                "Etherscan client is not available for current network %s",
                self.ethereum_network,
            )
            return None

    def get_blockscout_client(self) -> Optional[BlockscoutClient]:
        try:
            return BlockscoutClient(self.ethereum_network)
        except BlockScoutConfigurationProblem:
            logger.info(
                "Blockscout client is not available for current network %s",
                self.ethereum_network,
            )
            return None

    def get_sourcify_client(self) -> Optional[SourcifyClient]:
        try:
            return SourcifyClient(self.ethereum_network)
        except SourcifyClientConfigurationProblem:
            logger.info(
                "Sourcify client is not available for current network %s",
                self.ethereum_network,
            )
            return None
