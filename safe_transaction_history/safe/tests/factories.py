import os
import datetime
from logging import getLogger

import factory as factory_boy
from factory.fuzzy import FuzzyInteger, FuzzyNaiveDateTime
from faker import Factory as FakerFactory
from faker import Faker
from ethereum.transactions import secpk1n

from ..models import MultisigTransaction, MultisigConfirmation
from safe_transaction_history.ether.tests.factories import get_eth_address_with_key


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
    block_date_time = FuzzyNaiveDateTime(datetime.datetime.now())
    status = False
