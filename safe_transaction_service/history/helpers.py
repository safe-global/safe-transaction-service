import time
from typing import List

from eth_typing import ChecksumAddress
from eth_utils import keccak


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
