from django.utils import timezone

import factory
from eth_account import Account
from factory.fuzzy import FuzzyDateTime, FuzzyInteger
from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC, NULL_ADDRESS

from ..models import (EthereumBlock, EthereumEvent, EthereumTx,
                      EthereumTxCallType, EthereumTxType, InternalTx,
                      MultisigConfirmation, MultisigTransaction, ProxyFactory,
                      SafeContract, SafeMasterCopy, SafeStatus, WebHook)


class EthereumBlockFactory(factory.DjangoModelFactory):
    class Meta:
        model = EthereumBlock

    number = factory.Sequence(lambda n: n + 1)
    gas_limit = factory.fuzzy.FuzzyInteger(100000000, 200000000)
    gas_used = factory.fuzzy.FuzzyInteger(100000, 500000)
    timestamp = factory.LazyFunction(timezone.now)
    block_hash = factory.Sequence(lambda n: Web3.keccak(text=f'block-{n}').hex())
    parent_hash = factory.Sequence(lambda n: Web3.keccak(text=f'block{n - 1}').hex())


class EthereumTxFactory(factory.DjangoModelFactory):
    class Meta:
        model = EthereumTx

    block = factory.SubFactory(EthereumBlockFactory)
    tx_hash = factory.Sequence(lambda n: Web3.keccak(text=f'ethereum_tx_hash-{n}').hex())
    _from = factory.LazyFunction(lambda: Account.create().address)
    gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    gas_price = factory.fuzzy.FuzzyInteger(1, 100)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    nonce = factory.Sequence(lambda n: n)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)


class EthereumEventFactory(factory.DjangoModelFactory):
    class Meta:
        model = EthereumEvent

    class Params:
        to = None
        from_ = None
        erc721 = False
        value = 1200

    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    log_index = factory.Sequence(lambda n: n)
    address = factory.LazyFunction(lambda: Account.create().address)
    topic = ERC20_721_TRANSFER_TOPIC
    topics = [ERC20_721_TRANSFER_TOPIC]
    arguments = factory.LazyAttribute(lambda o: {'to': o.to if o.to else Account.create().address,
                                                 'from': o.from_ if o.from_ else Account.create().address,
                                                 'tokenId' if o.erc721 else 'value': o.value}
                                      )


class InternalTxFactory(factory.DjangoModelFactory):
    class Meta:
        model = InternalTx

    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    _from = factory.LazyFunction(lambda: Account.create().address)
    gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)
    gas_used = factory.fuzzy.FuzzyInteger(1000, 5000)
    contract_address = None
    code = None
    output = None
    refund_address = NULL_ADDRESS
    tx_type = EthereumTxType.CALL.value
    call_type = EthereumTxCallType.CALL.value
    trace_address = factory.Sequence(lambda n: n)
    error = None


class MultisigTransactionFactory(factory.DjangoModelFactory):
    class Meta:
        model = MultisigTransaction

    safe_tx_hash = factory.Sequence(lambda n: Web3.keccak(text=f'multisig-tx-{n}').hex())
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
    origin = factory.Faker('name')


class MultisigConfirmationFactory(factory.DjangoModelFactory):
    class Meta:
        model = MultisigConfirmation

    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    multisig_transaction = factory.SubFactory(MultisigTransaction)
    multisig_transaction_hash = factory.Sequence(lambda n: Web3.keccak(text=f'multisig-confirmation-tx-{n}').hex())
    owner = factory.LazyFunction(lambda: Account.create().address)


class SafeContractFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeContract

    address = factory.LazyFunction(lambda: Account.create().address)
    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    erc20_block_number = factory.LazyFunction(lambda: 0)


class MonitoredAddressFactory(factory.DjangoModelFactory):
    address = factory.LazyFunction(lambda: Account.create().address)
    initial_block_number = factory.LazyFunction(lambda: 0)
    tx_block_number = factory.LazyFunction(lambda: 0)


class ProxyFactoryFactory(MonitoredAddressFactory):
    class Meta:
        model = ProxyFactory


class SafeMasterCopyFactory(MonitoredAddressFactory):
    class Meta:
        model = SafeMasterCopy


class SafeStatusFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeStatus

    internal_tx = factory.SubFactory(InternalTxFactory)
    address = factory.LazyFunction(lambda: Account.create().address)
    owners = factory.LazyFunction(lambda: [Account.create().address for _ in range(4)])
    threshold = FuzzyInteger(low=1, high=2)
    nonce = factory.Sequence(lambda n: n)
    master_copy = factory.LazyFunction(lambda: Account.create().address)


class WebHookFactory(factory.DjangoModelFactory):
    class Meta:
        model = WebHook

    address = factory.LazyFunction(lambda: Account.create().address)
    url = 'http://localhost/test'
    # Configurable webhook types to listen to
    new_confirmation = True
    pending_outgoing_transaction = True
    new_executed_outgoing_transaction = True
    new_incoming_transaction = True
