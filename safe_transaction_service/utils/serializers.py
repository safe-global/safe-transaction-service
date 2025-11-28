from datetime import datetime

from eth_typing import ChecksumAddress
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import DateTimeField
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.safe import Safe
from web3.exceptions import Web3Exception


def get_safe_owners(safe_address: ChecksumAddress) -> list[ChecksumAddress]:
    """
    :param safe_address:
    :return: Current owners for a Safe
    :raises: ValidationError
    """
    ethereum_client = get_auto_ethereum_client()
    safe = Safe(safe_address, ethereum_client)
    try:
        return safe.retrieve_owners(block_identifier="latest")
    except Web3Exception as e:
        raise ValidationError(
            f"Could not get Safe {safe_address} owners from blockchain, check contract exists on network "
            f"{ethereum_client.get_network().name}"
        ) from e
    except OSError as exc:
        raise ValidationError(
            "Problem connecting to the ethereum node, please try again later"
        ) from exc


def select_preimage_by_safe_version(
    safe_version: str, safe_message_preimage: bytes
) -> bytes | None:
    """
    Returns None for v1.5.0+ Safes, otherwise returns the provided preimage.

    :param safe_version: Version of the Safe contract.
    :param message_hash: Original message hash (EIP-191 or EIP-712).
    :param safe_message_preimage: Safe-encoded message hash.
    :return: Hash to be used for signature validation.
    """
    if safe_version == "1.5.0":
        return None
    return safe_message_preimage


class EpochDateTimeField(DateTimeField):
    """
    Custom DateTimeField that accepts an integer epoch and converts it to a datetime.
    """

    def to_representation(self, value):
        if isinstance(value, int):
            value = datetime.fromtimestamp(value)

        return super().to_representation(value)
