from django.utils import timezone

import factory
from eth_account import Account
from factory.django import DjangoModelFactory

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import fast_keccak
from gnosis.safe.safe_signature import SafeSignatureType

from safe_transaction_service.history.tests import factories as history_factories

from .. import models
from ..constants import USER_OPERATION_SUPPORTED_ENTRY_POINTS


class UserOperationFactory(DjangoModelFactory):
    class Meta:
        model = models.UserOperation

    hash = factory.Sequence(
        lambda n: "0x" + fast_keccak(f"user-operation-{n}".encode()).hex()
    )
    ethereum_tx = factory.SubFactory(history_factories.EthereumTxFactory)
    sender = factory.LazyFunction(lambda: Account.create().address)
    nonce = factory.Sequence(lambda n: n)
    init_code = b""
    call_data = b""
    call_data_gas_limit = factory.fuzzy.FuzzyInteger(50_000, 200_000)
    verification_gas_limit = factory.fuzzy.FuzzyInteger(30_000, 50_000)
    pre_verification_gas = factory.fuzzy.FuzzyInteger(20_000, 30_000)
    max_fee_per_gas = factory.fuzzy.FuzzyInteger(20, 50)
    max_priority_fee_per_gas = factory.fuzzy.FuzzyInteger(0, 10)
    paymaster = NULL_ADDRESS
    paymaster_data = b""
    signature = b""
    entry_point = list(USER_OPERATION_SUPPORTED_ENTRY_POINTS)[0]


class UserOperationReceiptFactory(DjangoModelFactory):
    class Meta:
        model = models.UserOperationReceipt

    user_operation = factory.SubFactory(UserOperationFactory)


class SafeOperationFactory(DjangoModelFactory):
    class Meta:
        model = models.SafeOperation

    hash = factory.Sequence(
        lambda n: "0x" + fast_keccak(f"safe-operation-{n}".encode()).hex()
    )
    user_operation = factory.SubFactory(UserOperationFactory)
    valid_after = factory.LazyFunction(timezone.now)
    valid_until = factory.LazyFunction(timezone.now)
    module_address = factory.LazyFunction(lambda: Account.create().address)


class SafeOperationConfirmationFactory(DjangoModelFactory):
    class Meta:
        model = models.SafeOperationConfirmation

    class Params:
        signing_owner = Account.create()

    safe_operation = factory.SubFactory(SafeOperationFactory)
    owner = factory.LazyAttribute(lambda o: o.signing_owner.address)
    signature = factory.LazyAttribute(
        lambda o: o.signing_owner.signHash(o.safe_operation.hash)["signature"].hex()
    )
    signature_type = SafeSignatureType.EOA.value
