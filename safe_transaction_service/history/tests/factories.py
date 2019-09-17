from django.utils import timezone

import factory
from eth_account import Account
from factory.fuzzy import FuzzyDateTime, FuzzyInteger
from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS

from ..models import (ConfirmationType, EthereumBlock, EthereumTx,
                      MultisigConfirmation, MultisigTransaction)


class EthereumBlockFactory(factory.DjangoModelFactory):
    class Meta:
        model = EthereumBlock

    number = factory.Sequence(lambda n: n)
    gas_limit = factory.fuzzy.FuzzyInteger(100000000, 200000000)
    gas_used = factory.fuzzy.FuzzyInteger(100000, 500000)
    timestamp = factory.LazyFunction(timezone.now)
    block_hash = factory.Sequence(lambda n: Web3.sha3(text=f'block-{n}').hex())
    parent_hash = factory.Sequence(lambda n: Web3.sha3(text=f'block{n - 1}').hex())


class EthereumTxFactory(factory.DjangoModelFactory):
    class Meta:
        model = EthereumTx

    block = factory.SubFactory(EthereumBlockFactory)
    tx_hash = factory.Sequence(lambda n: Web3.sha3(text=f'ethereum_tx_hash-{n}').hex())
    _from = factory.LazyFunction(lambda: Account.create().address)
    gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    gas_price = factory.fuzzy.FuzzyInteger(1, 100)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    nonce = factory.Sequence(lambda n: n)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)


class MultisigTransactionFactory(factory.DjangoModelFactory):
    class Meta:
        model = MultisigTransaction

    safe_tx_hash = factory.Sequence(lambda n: Web3.sha3(text=f'multisig-tx-{n}').hex())
    safe = factory.LazyFunction(lambda: Account.create().address)
    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = FuzzyInteger(low=0, high=10)
    data = b''
    operation = FuzzyInteger(low=0, high=2)
    safe_tx_gas = FuzzyInteger(low=400000, high=500000)
    base_gas = FuzzyInteger(low=200000, high=300000)
    gas_price = FuzzyInteger(low=1, high=10)
    gas_token = NULL_ADDRESS
    refund_receiver = NULL_ADDRESS
    signatures = b''
    nonce = factory.Sequence(lambda n: n)


class MultisigConfirmationFactory(factory.DjangoModelFactory):
    class Meta:
        model = MultisigConfirmation

    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    multisig_transaction = factory.SubFactory(MultisigTransaction)
    multisig_transaction_hash = factory.Sequence(lambda n: Web3.sha3(text=f'multisig-confirmation-tx-{n}').hex())
    owner = factory.LazyFunction(lambda: Account.create().address)
