import datetime
from collections import OrderedDict
from enum import Enum
from logging import getLogger
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.db.models import Case, Q, Sum
from django.db.models.expressions import F, RawSQL, Value, When
from django.db.models.signals import post_save
from django.dispatch import receiver

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel

from gnosis.eth import EthereumClientProvider
from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC
from gnosis.eth.django.models import (EthereumAddressField, HexField,
                                      Sha3HashField, Uint256Field)
from gnosis.safe import SafeOperation

logger = getLogger(__name__)


class ConfirmationType(Enum):
    CONFIRMATION = 0
    EXECUTION = 1


class EthereumTxCallType(Enum):
    CALL = 0
    DELEGATE_CALL = 1

    @staticmethod
    def parse_call_type(call_type: str):
        if not call_type:
            return None
        elif call_type.lower() == 'call':
            return EthereumTxCallType.CALL
        elif call_type.lower() == 'delegatecall':
            return EthereumTxCallType.DELEGATE_CALL
        else:
            return None


class EthereumTxType(Enum):
    CALL = 0
    CREATE = 1
    SELF_DESTRUCT = 2

    @staticmethod
    def parse(tx_type: str):
        tx_type = tx_type.upper()
        if tx_type == 'CALL':
            return EthereumTxType.CALL
        elif tx_type == 'CREATE':
            return EthereumTxType.CREATE
        elif tx_type == 'SUICIDE':
            return EthereumTxType.SELF_DESTRUCT
        else:
            raise ValueError(f'{tx_type} is not a valid EthereumTxType')


class TransactionNotFoundException(Exception):
    def __init__(self, tx_hash: Union[str, bytes]):
        super().__init__(f'Cannot find tx with tx-hash={HexBytes(tx_hash).hex()}')


class TransactionWithoutBlockException(Exception):
    def __init__(self, tx_hash: Union[str, bytes]):
        super().__init__(f'Cannot find block for tx with tx-hash={HexBytes(tx_hash).hex()}')


class EthereumBlockManager(models.Manager):
    def get_or_create_from_block_number(self, block_number: int):
        try:
            return self.get(number=block_number)
        except self.model.DoesNotExist:
            ethereum_client = EthereumClientProvider()
            current_block_number = ethereum_client.current_block_number  # For reorgs
            block = ethereum_client.get_block(block_number)
            return self.create_from_block(block, current_block_number=current_block_number)

    def get_or_create_from_block(self, block: Dict[str, Any], current_block_number: Optional[int] = None):
        try:
            return self.get(number=block['number'])
        except self.model.DoesNotExist:
            return self.create_from_block(block, current_block_number=current_block_number)

    def create_from_block(self, block: Dict[str, Any], current_block_number: Optional[int] = None) -> 'EthereumBlock':
        # If confirmed, we will not check for reorgs in the future
        confirmed = (current_block_number - block['number']) >= 6 if current_block_number is not None else False
        return super().create(
            number=block['number'],
            gas_limit=block['gasLimit'],
            gas_used=block['gasUsed'],
            timestamp=datetime.datetime.fromtimestamp(block['timestamp'], datetime.timezone.utc),
            block_hash=block['hash'],
            parent_hash=block['parentHash'],
            confirmed=confirmed,
        )


class EthereumBlockQuerySet(models.QuerySet):
    def not_confirmed(self):
        return self.filter(confirmed=False).order_by('number')


class EthereumBlock(models.Model):
    objects = EthereumBlockManager.from_queryset(EthereumBlockQuerySet)()
    number = models.PositiveIntegerField(primary_key=True, unique=True)
    gas_limit = models.PositiveIntegerField()
    gas_used = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    block_hash = Sha3HashField(unique=True)
    parent_hash = Sha3HashField(unique=True)
    confirmed = models.BooleanField(default=False,
                                    db_index=True)  # For reorgs, True if `current_block_number` - `number` >= 6

    def __str__(self):
        return f'Block number={self.number} on {self.timestamp}'

    def set_confirmed(self, current_block_number: int):
        if (current_block_number - self.number) >= 6:
            self.confirmed = True
            self.save()


class EthereumTxManager(models.Manager):
    def create_or_update_from_tx_hashes(self, tx_hashes: List[Union[str, bytes]]) -> List['EthereumTx']:
        # Search first in database
        ethereum_txs_dict = OrderedDict.fromkeys([HexBytes(tx_hash).hex() for tx_hash in tx_hashes])
        db_ethereum_txs = self.filter(tx_hash__in=tx_hashes).exclude(block=None)
        for db_ethereum_tx in db_ethereum_txs:
            ethereum_txs_dict[db_ethereum_tx.tx_hash] = db_ethereum_tx

        # Retrieve from the node the txs missing from database
        tx_hashes_not_in_db = [tx_hash for tx_hash, ethereum_tx in ethereum_txs_dict.items() if not ethereum_tx]
        if not tx_hashes_not_in_db:
            return list(ethereum_txs_dict.values())

        ethereum_client = EthereumClientProvider()
        current_block_number = ethereum_client.current_block_number
        txs = ethereum_client.get_transactions(tx_hashes_not_in_db)
        tx_receipts = ethereum_client.get_transaction_receipts(tx_hashes_not_in_db)

        block_numbers = []
        for tx_hash, tx, tx_receipt in zip(tx_hashes, txs, tx_receipts):
            if not tx:
                raise TransactionNotFoundException(tx_hash)
            elif tx.get('blockNumber') is None or tx_receipt.get('blockNumber') is None:
                raise TransactionWithoutBlockException(tx_hash)
            block_numbers.append(tx['blockNumber'])

        blocks = ethereum_client.get_blocks(block_numbers)

        for tx, tx_receipt, block in zip(txs, tx_receipts, blocks):
            try:
                ethereum_tx = self.get(tx_hash=tx['hash'])
                # For txs stored before being mined
                if ethereum_tx.block is None:
                    ethereum_tx.block = EthereumBlock.objects.get_or_create_from_block(block, current_block_number=current_block_number)
                    ethereum_tx.gas_used = tx_receipt['gasUsed']
                    ethereum_tx.status = tx_receipt.get('status')
                    ethereum_tx.transaction_index = tx_receipt['transactionIndex']
                    ethereum_tx.save(update_fields=['block', 'gas_used', 'status', 'transaction_index'])
                ethereum_txs_dict[HexBytes(ethereum_tx.tx_hash).hex()] = ethereum_tx
            except self.model.DoesNotExist:
                ethereum_block = EthereumBlock.objects.get_or_create_from_block(block, current_block_number=current_block_number)
                ethereum_tx = self.create_from_tx_dict(tx, tx_receipt=tx_receipt, ethereum_block=ethereum_block)
                ethereum_txs_dict[HexBytes(ethereum_tx.tx_hash).hex()] = ethereum_tx
        return list(ethereum_txs_dict.values())

    def create_or_update_from_tx_hash(self, tx_hash: str) -> 'EthereumTx':
        ethereum_client = EthereumClientProvider()
        try:
            ethereum_tx = self.get(tx_hash=tx_hash)
            # For txs stored before being mined
            if ethereum_tx.block is None:
                tx_receipt = ethereum_client.get_transaction_receipt(tx_hash)
                ethereum_tx.block = EthereumBlock.objects.get_or_create_from_block_number(tx_receipt['blockNumber'])
                ethereum_tx.gas_used = tx_receipt['gasUsed']
                ethereum_tx.status = tx_receipt.get('status')
                ethereum_tx.transaction_index = tx_receipt['transactionIndex']
                ethereum_tx.save(update_fields=['block', 'gas_used', 'status', 'transaction_index'])
            return ethereum_tx
        except self.model.DoesNotExist:
            tx_receipt = ethereum_client.get_transaction_receipt(tx_hash)
            ethereum_block = EthereumBlock.objects.get_or_create_from_block_number(tx_receipt['blockNumber'])
            tx = ethereum_client.get_transaction(tx_hash)
            return self.create_from_tx_dict(tx, tx_receipt=tx_receipt, ethereum_block=ethereum_block)

    def create_from_tx_dict(self, tx: Dict[str, Any], tx_receipt: Optional[Dict[str, Any]] = None,
                            ethereum_block: Optional[EthereumBlock] = None) -> 'EthereumTx':
        return super().create(
            block=ethereum_block,
            tx_hash=HexBytes(tx['hash']).hex(),
            _from=tx['from'],
            gas=tx['gas'],
            gas_price=tx['gasPrice'],
            gas_used=tx_receipt and tx_receipt['gasUsed'],
            status=tx_receipt and tx_receipt.get('status'),
            transaction_index=tx_receipt and tx_receipt['transactionIndex'],
            data=HexBytes(tx.get('data') or tx.get('input')),
            nonce=tx['nonce'],
            to=tx.get('to'),
            value=tx['value'],
        )


class EthereumTx(TimeStampedModel):
    objects = EthereumTxManager()
    block = models.ForeignKey(EthereumBlock, on_delete=models.CASCADE, null=True, default=None,
                              related_name='txs')  # If mined
    tx_hash = Sha3HashField(unique=True, primary_key=True)
    gas_used = Uint256Field(null=True, default=None)  # If mined
    status = models.IntegerField(null=True, default=None)  # If mined. Old txs don't have `status`
    transaction_index = models.PositiveIntegerField(null=True, default=None)  # If mined
    _from = EthereumAddressField(null=True, db_index=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    data = models.BinaryField(null=True)
    nonce = Uint256Field()
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()

    def __str__(self):
        return '{} from={} to={}'.format(self.tx_hash, self._from, self.to)

    @property
    def success(self) -> Optional[bool]:
        if self.status is not None:
            return self.status == 1


class EthereumEventQuerySet(models.QuerySet):
    def not_erc_20_721_events(self):
        return self.exclude(topic=ERC20_721_TRANSFER_TOPIC)

    def erc20_and_721_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        queryset = self.filter(topic=ERC20_721_TRANSFER_TOPIC)
        if token_address:
            queryset = queryset.filter(address=token_address)
        if address:
            queryset = queryset.filter(Q(arguments__to=address) | Q(arguments__from=address))
        return queryset

    def erc20_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        return self.erc20_and_721_events(token_address=token_address,
                                         address=address).filter(arguments__has_key='value')

    def erc721_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        return self.erc20_and_721_events(token_address=token_address,
                                         address=address).filter(arguments__has_key='tokenId')


class EthereumEventManager(models.Manager):
    def from_decoded_event(self, decoded_event: Dict[str, Any]) -> 'EthereumEvent':
        """
        Does not create the model. Requires that `ethereum_tx` exists
        :param decoded_event:
        :return: `EthereumEvent` instance (not stored in database)
        """
        return EthereumEvent(ethereum_tx_id=decoded_event['transactionHash'],
                             log_index=decoded_event['logIndex'],
                             address=decoded_event['address'],
                             topic=decoded_event['topics'][0],
                             topics=decoded_event['topics'],
                             arguments=decoded_event['args'])

    def erc20_tokens_used_by_address(self, address: str) -> List[str]:
        """
        :param address:
        :return: List of token addresses used by an address
        """
        return self.erc20_events(address=address).values_list('address', flat=True).distinct()

    def erc20_tokens_with_balance(self, address: str) -> List[Dict[str, Any]]:
        """
        :return: List of dictionaries {'token_address': str, 'balance': int}
        """
        arguments_value_field = RawSQL("(arguments->>'value')::numeric", ())
        return self.erc20_events(
            address=address
        ).values('address').annotate(
            balance=Sum(Case(
                When(arguments__from=address, then=-arguments_value_field),
                default=arguments_value_field,
            ))
        ).order_by('-balance').values('address', 'balance')

    def get_or_create_erc20_or_721_event(self, decoded_event: Dict[str, Any]):
        if 'value' not in decoded_event['args'] or 'tokenId' not in decoded_event['args']:
            raise ValueError('Invalid ERC20 or ERC721 event %s' % decoded_event)
        else:
            return self.get_or_create(ethereum_tx_id=decoded_event['transactionHash'],
                                      log_index=decoded_event['logIndex'],
                                      defaults={
                                          'address': decoded_event['address'],
                                          'topic': decoded_event['topics'][0],
                                          'topics': decoded_event['topics'],
                                          'arguments': decoded_event['args'],
                                      })


class EthereumEvent(models.Model):
    objects = EthereumEventManager.from_queryset(EthereumEventQuerySet)()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='events')
    log_index = models.PositiveIntegerField()
    address = EthereumAddressField(db_index=True)
    topic = Sha3HashField(db_index=True)
    topics = ArrayField(Sha3HashField())
    arguments = JSONField()

    class Meta:
        unique_together = (('ethereum_tx', 'log_index'),)

    def __str__(self):
        return f'Tx-hash={self.ethereum_tx_id} Log-index={self.log_index} Topic={self.topic} Arguments={self.arguments}'

    def is_erc20(self) -> bool:
        return self.topic == ERC20_721_TRANSFER_TOPIC and 'value' in self.arguments

    def is_erc721(self) -> bool:
        return self.topic == ERC20_721_TRANSFER_TOPIC and 'tokenId' in self.arguments


class InternalTxManager(models.Manager):
    def build_from_trace(self, trace: Dict[str, Any], ethereum_tx: EthereumTx) -> 'InternalTx':
        tx_type = EthereumTxType.parse(trace['type'])
        call_type = EthereumTxCallType.parse_call_type(trace['action'].get('callType'))
        trace_address_str = ','.join([str(address) for address in trace['traceAddress']])
        return InternalTx(
            ethereum_tx=ethereum_tx,
            trace_address=trace_address_str,
            _from=trace['action'].get('from'),
            gas=trace['action'].get('gas', 0),
            data=trace['action'].get('input') or trace['action'].get('init'),
            to=trace['action'].get('to') or trace['action'].get('address'),
            value=trace['action'].get('value') or trace['action'].get('balance', 0),
            gas_used=(trace.get('result') or {}).get('gasUsed', 0),
            contract_address=(trace.get('result') or {}).get('address'),
            code=(trace.get('result') or {}).get('code'),
            output=(trace.get('result') or {}).get('output'),
            refund_address=trace['action'].get('refundAddress'),
            tx_type=tx_type.value,
            call_type=call_type.value if call_type else None,
            error=trace.get('error')
        )

    def get_or_create_from_trace(self, trace: Dict[str, Any], ethereum_tx: EthereumTx) -> Tuple['InternalTx', bool]:
        tx_type = EthereumTxType.parse(trace['type'])
        call_type = EthereumTxCallType.parse_call_type(trace['action'].get('callType'))
        trace_address_str = ','.join([str(address) for address in trace['traceAddress']])
        return self.get_or_create(
            ethereum_tx=ethereum_tx,
            trace_address=trace_address_str,
            defaults={
                '_from': trace['action'].get('from'),
                'gas': trace['action'].get('gas', 0),
                'data': trace['action'].get('input') or trace['action'].get('init'),
                'to': trace['action'].get('to') or trace['action'].get('address'),
                'value': trace['action'].get('value') or trace['action'].get('balance', 0),
                'gas_used': (trace.get('result') or {}).get('gasUsed', 0),
                'contract_address': (trace.get('result') or {}).get('address'),
                'code': (trace.get('result') or {}).get('code'),
                'output': (trace.get('result') or {}).get('output'),
                'refund_address': trace['action'].get('refundAddress'),
                'tx_type': tx_type.value,
                'call_type': call_type.value if call_type else None,
                'error': trace.get('error'),
            }
        )


class InternalTxQuerySet(models.QuerySet):
    def incoming_txs(self, address: str):
        return self.filter(to=address,
                           call_type=EthereumTxCallType.CALL.value,
                           value__gt=0
                           ).annotate(
            transaction_hash=F('ethereum_tx_id'),
            block_number=F('ethereum_tx__block_id'),
            token_address=Value(None, output_field=EthereumAddressField())
        ).order_by('-ethereum_tx__block_id')

    def incoming_txs_with_events(self, address: str):
        values = ('block_number', 'transaction_hash', 'to', '_from', 'value', 'token_address')
        ether_queryset = self.incoming_txs(address).values(*values)
        events_queryset = EthereumEvent.objects.erc20_events().filter(
            arguments__to=address
        ).annotate(
            to=RawSQL("arguments->>%s", ('to',)),  # Order is really important!
            _from=RawSQL("arguments->>%s", ('from',)),
            value=RawSQL("(arguments->>%s)::numeric", ('value',)),
            transaction_hash=F('ethereum_tx_id'),
            block_number=F('ethereum_tx__block_id'),
            token_address=F('address')
        ).order_by('-ethereum_tx__block_id').values(*values)

        return ether_queryset.union(events_queryset).order_by('-block_number')

    def can_be_decoded(self):
        return self.filter(
            call_type=EthereumTxCallType.DELEGATE_CALL.value,
            error=None,
            ethereum_tx__status=1,
            decoded_tx=None,
        ).exclude(data=None)


class InternalTx(models.Model):
    objects = InternalTxManager.from_queryset(InternalTxQuerySet)()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='internal_txs')
    _from = EthereumAddressField(null=True, db_index=True)  # For SELF-DESTRUCT it can be null
    gas = Uint256Field()
    data = models.BinaryField(null=True)  # `input` for Call, `init` for Create
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()
    gas_used = Uint256Field()
    contract_address = EthereumAddressField(null=True, db_index=True)  # Create
    code = models.BinaryField(null=True)                # Create
    output = models.BinaryField(null=True)              # Call
    refund_address = EthereumAddressField(null=True, db_index=True)  # For SELF-DESTRUCT
    tx_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in EthereumTxType], db_index=True)
    call_type = models.PositiveSmallIntegerField(null=True,
                                                 choices=[(tag.value, tag.name) for tag in EthereumTxCallType],
                                                 db_index=True)  # Call
    trace_address = models.CharField(max_length=100)  # Stringified traceAddress
    error = models.CharField(max_length=100, null=True)

    class Meta:
        unique_together = (('ethereum_tx', 'trace_address'),)

    def __str__(self):
        if self.to:
            return 'Internal tx hash={} from={} to={}'.format(self.ethereum_tx_id, self._from, self.to)
        else:
            return 'Internal tx hash={} from={}'.format(self.ethereum_tx_id, self._from)

    @property
    def block_number(self):
        return self.ethereum_tx.block_id

    @property
    def can_be_decoded(self):
        return (self.is_delegate_call
                and not self.error
                and self.data
                and self.ethereum_tx.success)

    @property
    def is_call(self):
        return EthereumTxType(self.tx_type) == EthereumTxType.CALL

    @property
    def is_decoded(self):
        try:
            return bool(self.decoded_tx)
        except InternalTxDecoded.DoesNotExist:
            return False

    @property
    def is_delegate_call(self) -> bool:
        if self.call_type is None:
            return False
        else:
            return EthereumTxCallType(self.call_type) == EthereumTxCallType.DELEGATE_CALL

    def get_next_trace(self) -> Optional['InternalTx']:
        internal_txs = InternalTx.objects.filter(ethereum_tx=self.ethereum_tx).order_by('trace_address')
        traces = [it.trace_address for it in internal_txs]
        index = traces.index(self.trace_address)
        try:
            return internal_txs[index + 1]
        except IndexError:
            return None

    def get_previous_trace(self) -> Optional['InternalTx']:
        internal_txs = InternalTx.objects.filter(ethereum_tx=self.ethereum_tx).order_by('trace_address')
        traces = [it.trace_address for it in internal_txs]
        index = traces.index(self.trace_address)
        try:
            return internal_txs[index - 1]
        except IndexError:
            return None


class InternalTxDecodedManager(models.Manager):
    pass


class InternalTxDecodedQuerySet(models.QuerySet):
    def not_processed(self):
        return self.filter(processed=False)

    def pending_for_safes(self):
        """
        :return: Pending `InternalTxDecoded` sorted by block number and then transaction index inside the block
        """
        return self.not_processed(
        ).filter(
            Q(internal_tx___from__in=SafeContract.objects.values('address'))  # Just Safes indexed
            | Q(function_name='setup')  # This way we can index new Safes without events
        ).select_related(
            'internal_tx',
            'internal_tx__ethereum_tx',
        ).order_by(
            'internal_tx__ethereum_tx__block_id',
            'internal_tx__ethereum_tx__transaction_index',
            'internal_tx__trace_address',
        )


class InternalTxDecoded(models.Model):
    objects = InternalTxDecodedManager.from_queryset(InternalTxDecodedQuerySet)()
    internal_tx = models.OneToOneField(InternalTx, on_delete=models.CASCADE, related_name='decoded_tx',
                                       primary_key=True)
    function_name = models.CharField(max_length=256)
    arguments = JSONField()
    processed = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Internal txs decoded"

    @property
    def address(self) -> str:
        return self.internal_tx._from

    @property
    def block_number(self) -> int:
        return self.internal_tx.ethereum_tx.block_id

    @property
    def tx_hash(self) -> str:
        return self.internal_tx.ethereum_tx_id

    def set_processed(self):
        self.processed = True
        return self.save(update_fields=['processed'])


class MultisigTransactionQuerySet(models.QuerySet):
    def executed(self):
        return self.exclude(
            ethereum_tx__block=None
        )

    def not_executed(self):
        return self.filter(
            ethereum_tx__block=None
        )


class MultisigTransaction(TimeStampedModel):
    objects = MultisigTransactionQuerySet.as_manager()
    safe_tx_hash = Sha3HashField(primary_key=True)
    safe = EthereumAddressField()
    ethereum_tx = models.ForeignKey(EthereumTx, null=True, default=None, blank=True,
                                    on_delete=models.SET_NULL, related_name='multisig_txs')
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in SafeOperation])
    safe_tx_gas = Uint256Field()
    base_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressField(null=True)
    refund_receiver = EthereumAddressField(null=True)
    signatures = models.BinaryField(null=True)  # When tx is executed
    nonce = Uint256Field()

    def __str__(self):
        return f'{self.safe} - {self.nonce} - {self.safe_tx_hash}'

    @property
    def execution_date(self) -> Optional[datetime.datetime]:
        if self.ethereum_tx_id and self.ethereum_tx.block:
            return self.ethereum_tx.block.timestamp
        return None

    @property
    def executed(self) -> bool:
        return bool(self.ethereum_tx_id and (self.ethereum_tx.block_id is not None))

    def owners(self) -> Optional[List[str]]:
        if not self.signatures:
            return None
        else:
            # TODO Get owners from signatures. Not very trivial
            return []


class MultisigConfirmationQuerySet(models.QuerySet):
    def without_transaction(self):
        return self.filter(multisig_transaction=None)

    def with_transaction(self):
        return self.exclude(multisig_transaction=None)


class MultisigConfirmation(TimeStampedModel):
    objects = MultisigConfirmationQuerySet.as_manager()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='multisig_confirmations',
                                    null=True)  # `null=True` for signature confirmations
    multisig_transaction = models.ForeignKey(MultisigTransaction,
                                             on_delete=models.CASCADE,
                                             null=True,
                                             related_name="confirmations")
    multisig_transaction_hash = Sha3HashField(null=True,
                                              db_index=True)  # Use this while we don't have a `multisig_transaction`
    owner = EthereumAddressField()

    signature = HexField(null=True, default=None, max_length=500)  # Off chain signatures

    class Meta:
        unique_together = (('multisig_transaction_hash', 'owner'),)

    def __str__(self):
        if self.multisig_transaction_id:
            return f'Confirmation of owner={self.owner} for transaction-hash={self.multisig_transaction_hash}'
        else:
            return f'Confirmation of owner={self.owner} for existing transaction={self.multisig_transaction_hash}'


@receiver(post_save, sender=MultisigConfirmation)
@receiver(post_save, sender=MultisigTransaction)
def bind_confirmation(sender: Type[models.Model], instance: Union[MultisigConfirmation, MultisigTransaction],
                      created: bool, **kwargs) -> None:
    """
    When a `MultisigConfirmation` is saved, it tries to bind it to an existing `MultisigTransaction`, and the opposite.
    :param sender: Could be MultisigConfirmation or MultisigTransaction
    :param instance: Instance of MultisigConfirmation or `MultisigTransaction`
    :param created: True if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """
    if not created:
        return
    if sender == MultisigTransaction:
        for multisig_confirmation in MultisigConfirmation.objects.without_transaction().filter(
                multisig_transaction_hash=instance.safe_tx_hash):
            multisig_confirmation.multisig_transaction = instance
            multisig_confirmation.save(update_fields=['multisig_transaction'])
    elif sender == MultisigConfirmation:
        if not instance.multisig_transaction_id:
            try:
                if instance.multisig_transaction_hash:
                    instance.multisig_transaction = MultisigTransaction.objects.get(
                        safe_tx_hash=instance.multisig_transaction_hash)
                    instance.save(update_fields=['multisig_transaction'])
            except MultisigTransaction.DoesNotExist:
                pass


class MonitoredAddressManager(models.Manager):
    def update_addresses(self, addresses: List[str], block_number: str, database_field: str) -> int:
        return self.filter(address__in=addresses).update(**{database_field: block_number})


class MonitoredAddressQuerySet(models.QuerySet):
    def almost_updated(self, database_field: str, current_block_number: int,
                       updated_blocks_behind: int, confirmations: int):
        return self.filter(
            **{database_field + '__lt': current_block_number - confirmations,
               database_field + '__gt': current_block_number - updated_blocks_behind})

    def not_updated(self, database_field: str, current_block_number: int, confirmations: int):
        return self.filter(
            **{database_field + '__lt': current_block_number - confirmations}
        )


class MonitoredAddress(models.Model):
    class Meta:
        abstract = True
        verbose_name_plural = "Monitored addresses"

    objects = MonitoredAddressManager.from_queryset(MonitoredAddressQuerySet)()
    address = EthereumAddressField(primary_key=True)
    initial_block_number = models.IntegerField(default=0)  # Block number when address received first tx
    tx_block_number = models.IntegerField(null=True, default=None)  # Block number when last internal tx scan ended

    def __str__(self):
        return f'Address={self.address} - Initial-block-number={self.initial_block_number}' \
               f' - Tx-block-number={self.tx_block_number}'


class ProxyFactory(MonitoredAddress):
    class Meta:
        verbose_name_plural = "Proxy factories"
        ordering = ['tx_block_number']


class SafeMasterCopy(MonitoredAddress):
    class Meta:
        verbose_name_plural = "Safe master copies"
        ordering = ['tx_block_number']


class SafeStatusManager(models.Manager):
    pass


class SafeStatusQuerySet(models.QuerySet):
    def last_for_address(self, address: str):
        safe_status = self.filter(
            address=address
        ).select_related(
            'internal_tx__ethereum_tx'
        ).order_by(
            'internal_tx__ethereum_tx__block_id',
            'internal_tx__ethereum_tx__transaction_index',
            'internal_tx_id',
        ).last()
        if not safe_status:
            logger.error('SafeStatus not found for address=%s', address)
        return safe_status


class SafeContractManager(MonitoredAddressManager):
    pass


class SafeContract(models.Model):
    objects = SafeContractManager.from_queryset(MonitoredAddressQuerySet)()
    address = EthereumAddressField(primary_key=True)
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='safe_contracts')
    erc20_block_number = models.IntegerField(default=0)  # Block number of last scan of erc20

    def __str__(self):
        return f'Safe address={self.address} - ethereum-tx={self.ethereum_tx_id}'

    @property
    def created_block_number(self) -> Optional[int]:
        if self.ethereum_tx:
            return self.ethereum_tx.block_id


@receiver(post_save, sender=SafeContract)
def safe_contract_receiver(sender: Type[models.Model], instance: SafeContract, created: bool, **kwargs) -> None:
    """
    When a `SafeContract` is saved, sets the `erc20_block_number` if not set
    :param sender: SafeContract
    :param instance: Instance of SafeContract
    :param created: True if model has just been created, `False` otherwise
    :param kwargs:
    :return:
    """
    if not created:
        return
    if sender == SafeContract:
        if instance.erc20_block_number == 0:
            if instance.ethereum_tx and instance.ethereum_tx.block_id:  # EthereumTx is mandatory, block is not
                instance.erc20_block_number = instance.ethereum_tx.block_id
                instance.save()


class SafeStatus(models.Model):
    objects = SafeStatusManager.from_queryset(SafeStatusQuerySet)()
    internal_tx = models.OneToOneField(InternalTx, on_delete=models.CASCADE, related_name='safe_status',
                                       primary_key=True)
    address = EthereumAddressField()
    owners = ArrayField(EthereumAddressField())
    threshold = Uint256Field()
    nonce = Uint256Field(default=0)
    master_copy = EthereumAddressField()

    class Meta:
        unique_together = (('internal_tx', 'address'),)
        verbose_name_plural = 'Safe statuses'

    @property
    def block_number(self):
        return self.internal_tx.ethereum_tx.block_id

    def __str__(self):
        return f'safe={self.address} threshold={self.threshold} owners={self.owners} nonce={self.nonce}'

    def store_new(self, internal_tx: InternalTx) -> None:
        self.internal_tx = internal_tx
        return self.save()
