import os
from logging import getLogger

import factory as factory_boy
from django.utils import timezone
from django_eth.tests.factories import get_eth_address_with_key
from ethereum.transactions import secpk1n
from factory.fuzzy import FuzzyDateTime, FuzzyInteger
from faker import Factory as FakerFactory
from faker import Faker

from ..models import MultisigConfirmation, MultisigTransaction

fakerFactory = FakerFactory.create()
faker = Faker()

logger = getLogger(__name__)


def generate_valid_s():
    while True:
        s = int(os.urandom(31).hex(), 16)
        if s <= (secpk1n - 1):
            return s


def get_eth_address() -> str:
    address, _ = get_eth_address_with_key()
    return address


def generate_multisig_transactions(quantity=100):
    for x in range(0, quantity):
        MultisigTransactionFactory()


class MultisigTransactionFactory(factory_boy.DjangoModelFactory):
    class Meta:
        model = MultisigTransaction

    safe = get_eth_address()
    to = get_eth_address()
    value = FuzzyInteger(low=0, high=10)
    data = b''
    operation = FuzzyInteger(low=0, high=3)
    nonce = FuzzyInteger(low=0, high=10)
    status = False


class MultisigTransactionConfirmationFactory(factory_boy.DjangoModelFactory):
    class Meta:
        model = MultisigConfirmation

    owner = get_eth_address()
    contract_transaction_hash = factory_boy.Sequence(lambda n: '{:066d}'.format(n))
    multisig_transaction = factory_boy.SubFactory(MultisigTransaction)
    block_number = 0
    block_date_time = FuzzyDateTime(timezone.now())
    status = False
