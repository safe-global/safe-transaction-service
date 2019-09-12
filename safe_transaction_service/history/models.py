import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.db.models.signals import post_save
from django.utils import timezone
from gnosis.eth import EthereumClientProvider

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel

from gnosis.eth.django.models import (EthereumAddressField, HexField,
                                      Sha3HashField, Uint256Field)
from gnosis.safe import SafeOperation


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
            raise ValueError('%s is not a valid EthereumTxType' % tx_type)


class EthereumBlockManager(models.Manager):
    def get_or_create_from_block_number(self, block_number: int):
        try:
            return self.get(number=block_number)
        except self.model.DoesNotExist:
            current_block_number = self.ethereum_client.current_block_number  # For reorgs
            block = self.ethereum_client.get_block(block_number)
            return self.create_from_block(block, current_block_number=current_block_number)

    def create_from_block(self, block: Dict[str, Any], current_block_number: Optional[int]) -> 'EthereumBlock':
        # If confirmed, we will not check for reorgs in the future
        confirmed = (current_block_number - block['number']) >= 6 if current_block_number else False
        return super().create(
            number=block['number'],
            gas_limit=block['gasLimit'],
            gas_used=block['gasUsed'],
            timestamp=datetime.datetime.fromtimestamp(block['timestamp'], datetime.timezone.utc),
            block_hash=block['hash'],
            parent_hash=block['parentHash'],
            confirmed=confirmed,
        )


class EthereumBlock(models.Model):
    objects = EthereumBlockManager()
    number = models.PositiveIntegerField(primary_key=True, unique=True)
    gas_limit = models.PositiveIntegerField()
    gas_used = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    block_hash = Sha3HashField(unique=True)
    parent_hash = Sha3HashField(unique=True)
    confirmed = models.BooleanField(default=False)  # For reorgs, True if `current_block_number` - `number` >= 6


class EthereumTxManager(models.Manager):
    def create_or_update_from_tx_hash(self, tx_hash: str) -> 'EthereumTx':
        ethereum_client = EthereumClientProvider()
        try:
            ethereum_tx = self.get(tx_hash=tx_hash)
            # For txs stored before being mined
            if ethereum_tx.block is None:
                tx_receipt = ethereum_client.get_transaction_receipt(tx_hash)
                ethereum_tx.block = EthereumBlock.objects.get_or_create_from_block_number(tx_receipt.blockNumber)
                ethereum_tx.gas_used = tx_receipt.gasUsed
                ethereum_tx.status = tx_receipt.status
                ethereum_tx.transaction_index = tx_receipt.transactionIndex
                ethereum_tx.save(update_fields=['block', 'gas_used', 'status', 'transaction_index'])
            return ethereum_tx
        except self.model.DoesNotExist:
            tx_receipt = ethereum_client.get_transaction_receipt(tx_hash)
            ethereum_block = EthereumBlock.objects.get_or_create_from_block_number(tx_receipt.blockNumber)
            tx = ethereum_client.get_transaction(tx_hash)
            return self.create_from_tx(tx, tx_hash, tx_receipt, ethereum_block)

    def create_from_tx(self, tx: Dict[str, Any], tx_hash: Union[bytes, str],
                       tx_receipt: Optional[Dict[str, Any]] = None,
                       ethereum_block: Optional[EthereumBlock] = None) -> 'EthereumTx':
        return super().create(
            block=ethereum_block,
            tx_hash=tx_hash,
            _from=tx['from'],
            gas=tx['gas'],
            gas_price=tx['gasPrice'],
            gas_used=tx_receipt and tx_receipt.gasUsed,
            status=tx_receipt and tx_receipt.status,
            transaction_index=tx_receipt and tx_receipt.transactionIndex,
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
    status = models.IntegerField(null=True, default=None)  # If mined
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


class EthereumEvent(models.Model):
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='events')
    log_index = models.PositiveIntegerField()
    address = EthereumAddressField(db_index=True)
    data = HexField(null=True, max_length=2048)
    first_topic = Sha3HashField(db_index=True)
    topics = ArrayField(Sha3HashField())

    class Meta:
        unique_together = (('ethereum_tx', 'log_index'),)

    def __str__(self):
        return f'Tx-hash={self.ethereum_tx_id} Log-index={self.log_index} Topics={self.topics} Data={self.data}'


class InternalTxManager(models.Manager):
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


class InternalTx(models.Model):
    objects = InternalTxManager()
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
        return (self.is_call
                and not self.is_delegate_call
                and not self.error
                and self.data)

    @property
    def is_call(self):
        return EthereumTxType(self.tx_type) == EthereumTxType.CALL

    @property
    def is_decoded(self):
        try:
            self.decoded_tx
            return True
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


class InternalTxDecodedQuerySet(models.QuerySet):
    def not_processed(self):
        return self.filter(processed=False)

    def pending(self):
        """
        :return: Pending `InternalTxDecoded` sorted by block number and then transaction index inside the block
        """
        return self.not_processed(
        ).filter(
            internal_tx__to__in=MonitoredAddress.objects.values('address')  #TODO Maybe not here?
        ).select_related(
            'internal_tx__ethereum_tx'
        ).order_by(
            'internal_tx__ethereum_tx__block_id',
            'internal_tx__ethereum_tx__transaction_index',
            'internal_tx_id',
        )


class InternalTxDecoded(models.Model):
    objects = InternalTxDecodedQuerySet.as_manager()
    internal_tx = models.OneToOneField(InternalTx, on_delete=models.CASCADE, related_name='decoded_tx',
                                       primary_key=True)
    function_name = models.CharField(max_length=256)
    arguments = JSONField()
    processed = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Internal Txs Decoded"

    @property
    def address(self):
        return self.internal_tx.to

    @property
    def block_number(self):
        return self.internal_tx.ethereum_tx.block_id

    def set_processed(self):
        self.processed = True
        self.save(update_fields=['processed'])


class MultisigTransactionManager(models.Manager):
    def create(self, **kwargs):
        multisig_transaction = super().create(**kwargs)
        for multisig_confirmation in MultisigConfirmation.objects.without_transaction().filter(
                multisig_transaction_hash=multisig_transaction.safe_tx_hash):
            multisig_confirmation.multisig_transaction = multisig_transaction
            multisig_confirmation.save(update_fields=['multisig_transaction'])
        return multisig_transaction


class MultisigTransaction(TimeStampedModel):
    objects = MultisigTransactionManager()
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
    signatures = models.BinaryField(null=True)
    nonce = Uint256Field()

    def __str__(self):
        return f'{self.safe} - {self.nonce} - {self.safe_tx_hash}'

    @property
    def execution_date(self) -> Optional[datetime.datetime]:
        if self.ethereum_tx and self.ethereum_tx.block:
            return self.ethereum_tx.block.timestamp
        return None

    @property
    def mined(self) -> Optional[bool]:
        return self.ethereum_tx and (self.ethereum_tx.block_id is not None)

    def set_mined(self):
        raise NotImplemented
        self.mined = True
        self.execution_date = timezone.now()
        self.save(update_fields=['mined', 'execution_date'])

        # Mark every confirmation as mined
        MultisigConfirmation.objects.filter(multisig_transaction=self).update(mined=True)


#TODO Maybe use signals
class MultisigConfirmationManager(models.Manager):
    def create(self, **kwargs):
        multisig_transaction = kwargs.get('multisig_transaction', None)
        if not multisig_transaction:
            try:
                multisig_transaction_hash = kwargs.get('multisig_transaction_hash', None)
                if multisig_transaction_hash:
                    kwargs['multisig_transaction'] = MultisigTransaction.objects.get(
                        safe_tx_hash=multisig_transaction_hash)
            except MultisigTransaction.DoesNotExist:
                pass
        return super().create(**kwargs)


class MultisigConfirmationQuerySet(models.QuerySet):
    def without_transaction(self):
        return self.filter(multisig_transaction=None)

    def with_transaction(self):
        return self.exclude(multisig_transaction=None)


#TODO Allow off-chain confirmations
class MultisigConfirmation(models.Model):
    objects = MultisigConfirmationManager.from_queryset(MultisigConfirmationQuerySet)()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='multisig_confirmations')
    multisig_transaction = models.ForeignKey(MultisigTransaction,
                                             on_delete=models.CASCADE,
                                             null=True,
                                             related_name="confirmations")
    multisig_transaction_hash = Sha3HashField(null=True,
                                              db_index=True)  # Use this while we don't have a `multisig_transaction`
    owner = EthereumAddressField()

    class Meta:
        unique_together = (('multisig_transaction_hash', 'owner'),)

    def __str__(self):
        if self.multisig_transaction_id:
            return f'Confirmation of owner={self.owner} for transaction-hash={self.multisig_transaction_hash}'
        else:
            return f'Confirmation of owner={self.owner} for existing transaction={self.multisig_transaction_hash}'


def bind_confirmation(sender, instance, created, **kwargs):
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


# TODO Use receiver decorator
post_save.connect(bind_confirmation, sender=MultisigConfirmation)
post_save.connect(bind_confirmation, sender=MultisigTransaction)


class MonitoredAddressManager(models.Manager):
    def create_from_address(self, address: str, initial_block_number: int,
                            ethereum_tx: EthereumTx = None) -> 'MonitoredAddress':
        monitored_address, _ = self.get_or_create(address=address,
                                                  defaults={
                                                      'ethereum_tx': ethereum_tx,
                                                      'initial_block_number': initial_block_number,
                                                      'tx_block_number': initial_block_number,
                                                      'events_block_number': initial_block_number,
                                                  })
        return monitored_address

    def update_addresses(self, addresses: List[str], block_number: str, database_field: str) -> int:
        self.filter(address__in=addresses).update(**{database_field: block_number})


class MonitoredAddressQuerySet(models.QuerySet):
    def almost_updated(self, current_block_number: int, database_field: str,
                       confirmations: int, updated_blocks_behind: int):
        return self.filter(
            **{database_field + '__lt': current_block_number - confirmations,
               database_field + '__gt': current_block_number - updated_blocks_behind})

    def not_updated(self, current_block_number: int, database_field: str, confirmations: int):
        return self.filter(
            **{database_field + '__lt': current_block_number - confirmations})


class MonitoredAddress(models.Model):
    objects = MonitoredAddressManager.from_queryset(MonitoredAddressQuerySet)()
    address = EthereumAddressField(primary_key=True)
    ethereum_tx = models.ForeignKey(EthereumTx, blank=True,
                                    null=True, on_delete=models.SET_NULL, related_name='monitored_addresses')
    initial_block_number = models.IntegerField(default=0)  # Block number when address received first tx
    tx_block_number = models.IntegerField(null=True, default=None)  # Block number when last internal tx scan ended
    events_block_number = models.IntegerField(null=True, default=None)  # Block number when last events scan ended

    class Meta:
        verbose_name_plural = "Monitored Addresses"

    def __str__(self):
        return f'Address={self.address} - Initial-block-number={self.initial_block_number}' \
               f' - Tx-block-number={self.tx_block_number} - Events-block-number={self.events_block_number}'


class SafeStatusQuerySet(models.QuerySet):
    def last_for_address(self, address: str):
        return self.filter(
            address=address
        ).select_related(
            'internal_tx__ethereum_tx'
        ).order_by(
            'internal_tx__ethereum_tx__block_id',
            'internal_tx__ethereum_tx__transaction_index',
            'internal_tx_id',
        ).last()


class SafeStatus(models.Model):
    objects = SafeStatusQuerySet.as_manager()
    internal_tx = models.OneToOneField(InternalTx, on_delete=models.CASCADE, related_name='safe_status',
                                       primary_key=True)
    address = EthereumAddressField()
    owners = ArrayField(EthereumAddressField())
    threshold = Uint256Field()
    nonce = Uint256Field(default=0)
    master_copy = EthereumAddressField()

    class Meta:
        unique_together = (('internal_tx', 'address'),)
        verbose_name_plural = 'Safe Statuses'

    @property
    def block_number(self):
        return self.internal_tx.ethereum_tx.block_id

    def __str__(self):
        return f'safe={self.address} threshold={self.threshold} owners={self.owners} nonce={self.nonce}'
