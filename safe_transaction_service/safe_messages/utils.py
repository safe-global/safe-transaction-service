from typing import Any

from eth_account.messages import encode_defunct
from eth_typing import ChecksumAddress, Hash32
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.eth.eip712 import eip712_encode
from safe_eth.safe import Safe


def encode_eip191_message(message: str) -> bytes:
    signable_message = encode_defunct(text=message)
    return (
        b"\x19"
        + signable_message.version
        + signable_message.header
        + signable_message.body
    )


def encode_eip712_message(message: dict[str, Any]) -> bytes:
    return b"".join(eip712_encode(message))


def get_message_encoded(message: str | dict[str, Any]) -> bytes:
    return (
        encode_eip191_message(message)
        if isinstance(message, str)
        else encode_eip712_message(message)
    )


def get_safe_message_hash_and_preimage_for_message(
    safe_address: ChecksumAddress, message: bytes
) -> tuple[Hash32, bytes]:
    safe = Safe(safe_address, get_auto_ethereum_client())
    return safe.get_message_hash_and_preimage(message)


def select_hash_by_safe_version(
    safe_version: str, safe_message_hash: bytes, safe_message_preimage: bytes
) -> bytes:
    """
    Returns the Safe-encoded message hash for v1.5.0+ Safes, otherwise returns the provided preimage.

    :param safe_version: Version of the Safe contract.
    :param safe_message_preimage: Safe-encoded message hash.
    :return: Hash to be used for signature validation.
    """
    if safe_version == "1.5.0":
        return safe_message_hash
    return safe_message_preimage
