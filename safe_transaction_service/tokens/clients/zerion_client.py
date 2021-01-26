from dataclasses import dataclass
from typing import List, Optional

from eth_typing import ChecksumAddress
from web3.exceptions import ContractLogicError

from gnosis.eth import EthereumClient


@dataclass
class UniswapComponent:
    address: str
    tokenType: str  # `ERC20` by default
    rate: str  # price per full share (1e18)


@dataclass
class UniswapPoolMetadata:
    address: ChecksumAddress
    name: str
    symbol: str
    decimals: int


class ZerionUniswapV2TokenAdapterClient:
    """
    Client for Zerion Uniswap V2 Token Adapter
    https://github.com/zeriontech/defi-sdk
    """
    abi = [{'inputs': [{'internalType': 'address', 'name': 'token', 'type': 'address'}],
            'name': 'getComponents',
            'outputs': [{'components': [{'internalType': 'address',
                                         'name': 'token',
                                         'type': 'address'},
                                        {'internalType': 'string', 'name': 'tokenType', 'type': 'string'},
                                        {'internalType': 'uint256', 'name': 'rate', 'type': 'uint256'}],
                         'internalType': 'struct Component[]',
                         'name': '',
                         'type': 'tuple[]'}],
            'stateMutability': 'view',
            'type': 'function'},
           {'inputs': [{'internalType': 'address', 'name': 'token', 'type': 'address'}],
            'name': 'getMetadata',
            'outputs': [{'components': [{'internalType': 'address',
                                         'name': 'token',
                                         'type': 'address'},
                                        {'internalType': 'string', 'name': 'name', 'type': 'string'},
                                        {'internalType': 'string', 'name': 'symbol', 'type': 'string'},
                                        {'internalType': 'uint8', 'name': 'decimals', 'type': 'uint8'}],
                         'internalType': 'struct TokenMetadata',
                         'name': '',
                         'type': 'tuple'}],
            'stateMutability': 'view',
            'type': 'function'}]
    mainnet_address = '0x6C5D49157863f942A5E6115aaEAb7d6A67a852d3'

    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client
        self.contract = ethereum_client.w3.eth.contract(self.mainnet_address, abi=self.abi)

    def get_components(self, token_address: ChecksumAddress) -> Optional[List[UniswapComponent]]:
        try:
            return [UniswapComponent(*component) for component
                    in self.contract.functions.getComponents(token_address).call()]
        except ContractLogicError:
            return None

    def get_metadata(self, token_address: ChecksumAddress) -> Optional[UniswapPoolMetadata]:
        try:
            return UniswapPoolMetadata(*self.contract.functions.getMetadata(token_address).call())
        except ContractLogicError:
            return None
