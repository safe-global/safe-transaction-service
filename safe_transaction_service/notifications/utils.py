from typing import Sequence

from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClientProvider
from gnosis.safe import Safe


def get_safe_owners(safe_address: str) -> Sequence[str]:
    ethereum_client = EthereumClientProvider()
    safe = Safe(safe_address, ethereum_client)
    try:
        return safe.retrieve_owners(block_identifier='pending')
    except BadFunctionCallOutput:  # Error using pending block identifier
        return safe.retrieve_owners(block_identifier='latest')
