from typing import List

from eth_typing import ChecksumAddress
from rest_framework.exceptions import ValidationError
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.safe import Safe
from web3.exceptions import Web3Exception


def get_safe_owners(safe_address: ChecksumAddress) -> List[ChecksumAddress]:
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
    except IOError:
        raise ValidationError(
            "Problem connecting to the ethereum node, please try again later"
        )
