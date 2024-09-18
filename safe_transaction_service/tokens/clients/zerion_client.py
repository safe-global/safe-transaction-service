from dataclasses import dataclass
from typing import List, Optional

from eth_typing import ChecksumAddress
from safe_eth.eth import EthereumClient
from safe_eth.eth.constants import NULL_ADDRESS
from web3.exceptions import ContractLogicError


@dataclass
class UniswapComponent:
    address: str
    tokenType: str  # `ERC20` by default
    rate: str  # price per full share (1e18)


@dataclass
class ZerionPoolMetadata:
    address: ChecksumAddress
    name: str
    symbol: str
    decimals: int


class ZerionTokenAdapterClient:
    """
    Client for Zerion Token Adapter
    https://github.com/zeriontech/defi-sdk
    """

    ABI = [
        {
            "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
            "name": "getComponents",
            "outputs": [
                {
                    "components": [
                        {"internalType": "address", "name": "token", "type": "address"},
                        {
                            "internalType": "string",
                            "name": "tokenType",
                            "type": "string",
                        },
                        {"internalType": "uint256", "name": "rate", "type": "uint256"},
                    ],
                    "internalType": "struct Component[]",
                    "name": "",
                    "type": "tuple[]",
                }
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
            "name": "getMetadata",
            "outputs": [
                {
                    "components": [
                        {"internalType": "address", "name": "token", "type": "address"},
                        {"internalType": "string", "name": "name", "type": "string"},
                        {"internalType": "string", "name": "symbol", "type": "string"},
                        {"internalType": "uint8", "name": "decimals", "type": "uint8"},
                    ],
                    "internalType": "struct TokenMetadata",
                    "name": "",
                    "type": "tuple",
                }
            ],
            "stateMutability": "view",
            "type": "function",
        },
    ]
    ADAPTER_ADDRESS: ChecksumAddress = ChecksumAddress(NULL_ADDRESS)

    def __init__(
        self,
        ethereum_client: EthereumClient,
        adapter_address: Optional[ChecksumAddress] = None,
    ):
        self.ethereum_client = ethereum_client
        self.adapter_address = (
            adapter_address if adapter_address else self.ADAPTER_ADDRESS
        )
        self.contract = ethereum_client.w3.eth.contract(
            self.adapter_address, abi=self.ABI
        )

    def get_components(
        self, token_address: ChecksumAddress
    ) -> Optional[List[UniswapComponent]]:
        try:
            return [
                UniswapComponent(*component)
                for component in self.contract.functions.getComponents(
                    token_address
                ).call()
            ]
        except ContractLogicError:
            return None

    def get_metadata(
        self, token_address: ChecksumAddress
    ) -> Optional[ZerionPoolMetadata]:
        try:
            return ZerionPoolMetadata(
                *self.contract.functions.getMetadata(token_address).call()
            )
        except ContractLogicError:
            return None


class ZerionUniswapV2TokenAdapterClient(ZerionTokenAdapterClient):
    ADAPTER_ADDRESS: ChecksumAddress = ChecksumAddress(
        "0x6C5D49157863f942A5E6115aaEAb7d6A67a852d3"
    )


class BalancerTokenAdapterClient(ZerionTokenAdapterClient):
    ADAPTER_ADDRESS: ChecksumAddress = ChecksumAddress(
        "0xb45c5AE417F70E4C52DFB784569Ce843a45FE8ca"
    )
