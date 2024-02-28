import factory
from eth_account import Account
from factory.django import DjangoModelFactory

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import fast_keccak

from .. import models
from ..constants import USER_OPERATION_SUPPORTED_ENTRY_POINTS


class UserOperation(DjangoModelFactory):
    class Meta:
        model = models.UserOperation

    user_operation_hash = factory.Sequence(
        lambda n: fast_keccak(f"user-operation-{n}".encode()).hex()
    )
    sender = factory.LazyFunction(lambda: Account.create().address)
    paymaster = NULL_ADDRESS
    entry_point = USER_OPERATION_SUPPORTED_ENTRY_POINTS[0]


class UserOperationReceipt(DjangoModelFactory):
    class Meta:
        model = models.UserOperationReceipt
