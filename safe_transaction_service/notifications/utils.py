from typing import Sequence
from uuid import UUID

from hexbytes import HexBytes
from web3 import Web3


def calculate_device_registration_hash(
    timestamp: int,
    identifier: UUID,
    cloud_messaging_token: str,
    safes: Sequence[str],
    prefix: str = "gnosis-safe",
) -> HexBytes:
    safes_to_str = "".join(sorted(safes))
    str_to_sign = (
        f"{prefix}{timestamp}{identifier}{cloud_messaging_token}{safes_to_str}"
    )
    return Web3.keccak(text=str_to_sign)
