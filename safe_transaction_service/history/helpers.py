import re
import time
from typing import List

from eth_typing import ChecksumAddress
from eth_utils import keccak

from safe_transaction_service.history.models import TransferDict
from safe_transaction_service.tokens.models import Token


class DelegateSignatureHelper:
    @classmethod
    def calculate_totp(
        cls, totp_tx: int = 3600, totp_t0: int = 0, previous: bool = False
    ) -> int:
        """
        https://en.wikipedia.org/wiki/Time-based_One-time_Password_algorithm

        :param totp_tx: the Unix time from which to start counting time steps (default is 0)
        :param totp_t0: an interval which will be used to calculate the value of the
            counter CT (default is 3600 seconds).
        :param previous: Calculate totp for the previous interval
        :return: totp
        """
        if previous:
            totp_t0 += totp_tx  # Allow previous interval

        return int((time.time() - totp_t0) // totp_tx)

    @classmethod
    def calculate_hash(
        cls,
        address: ChecksumAddress,
        eth_sign: bool = False,
        previous_totp: bool = False,
    ) -> bytes:
        totp = cls.calculate_totp(previous=previous_totp)
        message = address + str(totp)
        if eth_sign:
            return keccak(
                text="\x19Ethereum Signed Message:\n" + str(len(message)) + message
            )
        else:
            return keccak(text=message)

    @classmethod
    def calculate_all_possible_hashes(cls, delegate: ChecksumAddress) -> List[bytes]:
        return [
            cls.calculate_hash(delegate),
            cls.calculate_hash(delegate, eth_sign=True),
            cls.calculate_hash(delegate, previous_totp=True),
            cls.calculate_hash(delegate, eth_sign=True, previous_totp=True),
        ]


def is_valid_unique_transfer_id(unique_transfer_id: str) -> bool:
    """
    Check if transfer_id starts with 'e' or 'i' followed by keccak256 and ended by digits or digits separated by commas

    :param unique_transfer_id:
    :return: ``True`` for a valid ``unique_transfer_id``, ``False`` otherwise
    """
    token_transfer_id_pattern = r"^(e)([a-fA-F0-9]{64})(\d+)"
    internal_transfer_id_pattern = r"^(i)([a-fA-F0-9]{64})(\d+)(,\d+)*"

    return bool(
        re.fullmatch(token_transfer_id_pattern, unique_transfer_id)
        or re.fullmatch(internal_transfer_id_pattern, unique_transfer_id)
    )


def add_tokens_to_transfers(transfers: TransferDict) -> TransferDict:
    """
    Add tokens to transfer if is a token transfer

    :param transfers:
    :return: transfers with tokens
    """
    tokens = {
        token.address: token
        for token in Token.objects.filter(
            address__in={
                transfer["token_address"]
                for transfer in transfers
                if transfer["token_address"]
            }
        )
    }
    for transfer in transfers:
        transfer["token"] = tokens.get(transfer["token_address"])
    return transfers
