from typing import Any, Dict

from eth_account.messages import defunct_hash_message
from eth_typing import ChecksumAddress, Hash32
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.eth.eip712 import eip712_encode_hash
from safe_eth.safe import Safe


def get_hash_for_message(message: str | Dict[str, Any]) -> Hash32:
    return (
        defunct_hash_message(text=message)
        if isinstance(message, str)
        else eip712_encode_hash(message)
    )


def get_safe_message_hash_for_message(
    safe_address: ChecksumAddress, message_hash: Hash32
) -> Hash32:
    safe = Safe(safe_address, get_auto_ethereum_client())
    return safe.get_message_hash(message_hash)
