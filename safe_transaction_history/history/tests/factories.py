import factory
from django.utils import timezone
from eth_account import Account
from factory.fuzzy import FuzzyDateTime, FuzzyInteger

from ..models import (HistoryOperation, MultisigConfirmation,
                      MultisigTransaction)


class MultisigTransactionFactory(factory.DjangoModelFactory):
    class Meta:
        model = MultisigTransaction

    safe = factory.LazyFunction(lambda: Account.create().address)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = FuzzyInteger(low=0, high=10)
    data = b''
    operation = FuzzyInteger(low=0, high=3)
    safe_tx_gas = FuzzyInteger(low=400000, high=500000)
    data_gas = FuzzyInteger(low=400000, high=500000)
    gas_price = FuzzyInteger(low=1, high=10)
    gas_token = '0x' + '0' * 40
    refund_receiver = '0x' + '0' * 40
    nonce = factory.Sequence(lambda n: n)
    mined = False


class MultisigTransactionConfirmationFactory(factory.DjangoModelFactory):
    class Meta:
        model = MultisigConfirmation

    owner = factory.LazyFunction(lambda: Account.create().address)
    contract_transaction_hash = factory.Sequence(lambda n: '{:064d}'.format(n))
    multisig_transaction = factory.SubFactory(MultisigTransaction)
    block_number = 0
    block_date_time = FuzzyDateTime(timezone.now())
    mined = False
    type = HistoryOperation.CONFIRMATION.value
