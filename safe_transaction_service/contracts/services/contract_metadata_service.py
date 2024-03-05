import logging
from functools import cache
from typing import Optional

from django.conf import settings

from eth_typing import ChecksumAddress

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.clients import (
    BlockscoutClient,
    BlockScoutConfigurationProblem,
    ContractMetadata,
    EtherscanClient,
    EtherscanClientConfigurationProblem,
    SourcifyClient,
    SourcifyClientConfigurationProblem,
)

logger = logging.getLogger(__name__)


@cache
def get_contract_metadata_service():
    return ContractMetadataService(EthereumClientProvider(), settings.ETHERSCAN_API_KEY)


class ContractMetadataService:
    def __init__(
        self, ethereum_client: EthereumClient, etherscan_api_key: Optional[str] = None
    ):
        self.ethereum_client = ethereum_client
        self.ethereum_network = ethereum_client.get_network()
        self.etherscan_api_key = etherscan_api_key
        self.etherscan_client = self._get_etherscan_client()
        self.blockscout_client = self._get_blockscout_client()
        self.sourcify_client = self._get_sourcify_client()
        self.enabled_clients = [
            client
            for client in (
                self.sourcify_client,
                self.etherscan_client,
                self.blockscout_client,
            )
            if client
        ]

    def _get_etherscan_client(self) -> Optional[EthereumClient]:
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

    def _get_blockscout_client(self) -> Optional[BlockscoutClient]:
        try:
            return BlockscoutClient(self.ethereum_network)
        except BlockScoutConfigurationProblem:
            logger.info(
                "Blockscout client is not available for current network %s",
                self.ethereum_network,
            )
            return None

    def _get_sourcify_client(self) -> Optional[SourcifyClient]:
        try:
            return SourcifyClient(self.ethereum_network)
        except SourcifyClientConfigurationProblem:
            logger.info(
                "Sourcify client is not available for current network %s",
                self.ethereum_network,
            )
            return None

    def get_contract_metadata(
        self, contract_address: ChecksumAddress
    ) -> Optional[ContractMetadata]:
        """
        Get contract metadata from every enabled client

        :param contract_address: Contract address
        :return: Contract Metadata if found from any client, otherwise None
        """
        for client in self.enabled_clients:
            try:
                contract_metadata = client.get_contract_metadata(contract_address)
                if contract_metadata:
                    return contract_metadata
            except IOError:
                logger.debug(
                    "Cannot get metadata for contract=%s on network=%s using client=%s",
                    contract_address,
                    self.ethereum_network.name,
                    client.__class__.__name__,
                )

        return None
