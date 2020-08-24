import functools

from rest_framework import status
from rest_framework.response import Response
from web3 import Web3


def ethereum_address_checksum_validator(func):
    @functools.wraps(func)
    def wrapped(self, *args, **kwargs):
        address = self.kwargs['address']  # Ethereum address should be `address` in the url
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            data={'code': 1,
                                  'message': 'Checksum address validation failed',
                                  'arguments': [address]})
        return func(self, *args, **kwargs)
    return wrapped
