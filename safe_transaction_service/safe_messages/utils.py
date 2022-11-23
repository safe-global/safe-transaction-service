from typing import Any, Dict

from eth_account.messages import defunct_hash_message
from eth_typing import ChecksumAddress, Hash32

from gnosis.eth import EthereumClientProvider
from gnosis.eth.eip712 import eip712_encode_hash
from gnosis.safe import Safe


def get_safe_message_hash_for_message(
    safe_address: ChecksumAddress, message: str | Dict[str, Any]
) -> Hash32:
    message_hash: Hash32 = (
        defunct_hash_message(text=message)
        if isinstance(message, str)
        else eip712_encode_hash(message)
    )
    safe = Safe(safe_address, EthereumClientProvider())
    return safe.get_message_hash(message_hash)
