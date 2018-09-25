import factory as factory_boy
from django.utils import timezone
from django_eth.tests.factories import get_eth_address_with_key
from factory.fuzzy import FuzzyDateTime, FuzzyInteger

from ..models import MultisigConfirmation, MultisigTransaction


def generate_multisig_transactions(quantity=100):
    return [MultisigTransactionFactory() for _ in range(quantity)]


class MultisigTransactionFactory(factory_boy.DjangoModelFactory):
    class Meta:
        model = MultisigTransaction

    safe, _ = get_eth_address_with_key()
    to, _ = get_eth_address_with_key()
    value = FuzzyInteger(low=0, high=10)
    data = b''
    operation = FuzzyInteger(low=0, high=3)
    nonce = FuzzyInteger(low=0, high=10)
    status = False


class MultisigTransactionConfirmationFactory(factory_boy.DjangoModelFactory):
    class Meta:
        model = MultisigConfirmation

    owner, _ = get_eth_address_with_key()
    contract_transaction_hash = factory_boy.Sequence(lambda n: '{:064d}'.format(n))
    multisig_transaction = factory_boy.SubFactory(MultisigTransaction)
    block_number = 0
    block_date_time = FuzzyDateTime(timezone.now())
    status = False
