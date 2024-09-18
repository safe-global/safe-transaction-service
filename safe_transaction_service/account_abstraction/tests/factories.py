from django.conf import settings
from django.utils import timezone

import factory
from eth_abi.packed import encode_packed
from eth_account import Account
from factory.django import DjangoModelFactory
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.utils import fast_keccak_text
from safe_eth.safe.safe_signature import SafeSignatureType

from safe_transaction_service.history.tests import factories as history_factories

from .. import models


class UserOperationFactory(DjangoModelFactory):
    class Meta:
        model = models.UserOperation

    class Params:
        # `valid_after` and `valid_until` are params for `SafeOperation` derivated from `UserOperation` signature
        valid_after = 0
        valid_until = 0

    hash = factory.Sequence(lambda n: fast_keccak_text(f"user-operation-{n}").hex())
    ethereum_tx = factory.SubFactory(history_factories.EthereumTxFactory)
    sender = factory.LazyFunction(lambda: Account.create().address)
    nonce = factory.Sequence(lambda n: n)
    init_code = b""
    call_data = b""
    call_gas_limit = factory.fuzzy.FuzzyInteger(50_000, 200_000)
    verification_gas_limit = factory.fuzzy.FuzzyInteger(30_000, 50_000)
    pre_verification_gas = factory.fuzzy.FuzzyInteger(20_000, 30_000)
    max_fee_per_gas = factory.fuzzy.FuzzyInteger(20, 50)
    max_priority_fee_per_gas = factory.fuzzy.FuzzyInteger(0, 10)
    paymaster = NULL_ADDRESS
    paymaster_data = b""
    entry_point = settings.ETHEREUM_4337_SUPPORTED_ENTRY_POINTS[0]

    @factory.lazy_attribute
    def signature(self):
        return encode_packed(["uint48"] * 2, [self.valid_after, self.valid_until])


class UserOperationReceiptFactory(DjangoModelFactory):
    class Meta:
        model = models.UserOperationReceipt

    user_operation = factory.SubFactory(UserOperationFactory)
    actual_gas_cost = factory.fuzzy.FuzzyInteger(20, 50)
    actual_gas_used = factory.fuzzy.FuzzyInteger(100, 200)
    success = True
    reason = ""
    deposited = factory.fuzzy.FuzzyInteger(500, 1_000)


class SafeOperationFactory(DjangoModelFactory):
    class Meta:
        model = models.SafeOperation

    hash = factory.Sequence(lambda n: fast_keccak_text(f"safe-operation-{n}").hex())
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
        lambda o: o.signing_owner.signHash(o.safe_operation.hash)["signature"]
    )
    signature_type = SafeSignatureType.EOA.value
