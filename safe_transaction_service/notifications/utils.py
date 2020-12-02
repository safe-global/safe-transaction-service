from typing import Sequence
from uuid import UUID

from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClientProvider
from gnosis.safe import Safe


def get_safe_owners(safe_address: str) -> Sequence[str]:
    ethereum_client = EthereumClientProvider()
    safe = Safe(safe_address, ethereum_client)
    try:
        return safe.retrieve_owners(block_identifier='pending')
    except BadFunctionCallOutput:  # Error using pending block identifier
        try:
            return safe.retrieve_owners(block_identifier='latest')
        except BadFunctionCallOutput:
            return []


def calculate_device_registration_hash(timestamp: int, identifier: UUID, cloud_messaging_token: str,
                                       safes: Sequence[str], prefix: str = 'gnosis-safe') -> HexBytes:
    safes_to_str = ''.join(sorted(safes))
    str_to_sign = f'{prefix}{timestamp}{identifier}{cloud_messaging_token}{safes_to_str}'
    return Web3.keccak(text=str_to_sign)
