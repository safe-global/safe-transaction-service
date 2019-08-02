import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.utils import timezone
from gnosis.eth.django.models import (EthereumAddressField, HexField,
                                      Sha3HashField, Uint256Field)
from gnosis.safe import SafeOperation
from hexbytes import HexBytes
from model_utils.models import TimeStampedModel


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
    def create_from_block(self, block: Dict[str, Any]) -> 'EthereumBlock':
        return super().create(
            number=block['number'],
            gas_limit=block['gasLimit'],
            gas_used=block['gasUsed'],
            timestamp=datetime.datetime.fromtimestamp(block['timestamp'], datetime.timezone.utc),
            block_hash=block['hash'],
        )


class EthereumBlock(models.Model):
    objects = EthereumBlockManager()
    number = models.PositiveIntegerField(primary_key=True, unique=True)
    gas_limit = models.PositiveIntegerField()
    gas_used = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    block_hash = Sha3HashField(unique=True)


class EthereumTxManager(models.Manager):
    def create_from_tx(self, tx: Dict[str, Any], tx_hash: Union[bytes, str], gas_used: Optional[int] = None,
                       ethereum_block: Optional[EthereumBlock] = None):
        return super().create(
            block=ethereum_block,
            tx_hash=tx_hash,
            _from=tx['from'],
            gas=tx['gas'],
            gas_price=tx['gasPrice'],
            gas_used=gas_used,
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
    def get_or_create_from_trace(self, trace: Dict[str, Any], ethereum_tx: EthereumTx):
        tx_type = EthereumTxType.parse(trace['type'])
        call_type = EthereumTxCallType.parse_call_type(trace['action'].get('callType'))
        trace_address_str = ','.join([str(address) for address in trace['traceAddress']])
        internal_tx, _ = self.get_or_create(
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
        return internal_tx


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
    tx_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in EthereumTxType])
    call_type = models.PositiveSmallIntegerField(null=True,
                                                 choices=[(tag.value, tag.name) for tag in EthereumTxCallType])  # Call
    trace_address = models.CharField(max_length=100)  # Stringified traceAddress
    error = models.CharField(max_length=100, null=True)

    class Meta:
        unique_together = (('ethereum_tx', 'trace_address'),)

    def __str__(self):
        if self.to:
            return 'Internal tx hash={} from={} to={}'.format(self.ethereum_tx.tx_hash, self._from, self.to)
        else:
            return 'Internal tx hash={} from={}'.format(self.ethereum_tx.tx_hash, self._from)


class MultisigTransaction(TimeStampedModel):
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
    nonce = Uint256Field()
    mined = models.BooleanField(default=False)  # True if transaction executed, 0 otherwise
    # Defines when a multisig transaction gets executed (confirmations included)
    execution_date = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        executed = 'Executed' if self.mined else 'Pending'
        return f'{self.safe} - {self.nonce} - {self.safe_tx_hash} - {executed}'

    def set_mined(self):
        self.mined = True
        self.execution_date = timezone.now()
        self.save(update_fields=['mined', 'execution_date'])

        # Mark every confirmation as mined
        MultisigConfirmation.objects.filter(multisig_transaction=self).update(mined=True)


class MultisigConfirmation(TimeStampedModel):
    multisig_transaction = models.ForeignKey(MultisigTransaction,
                                             on_delete=models.CASCADE,
                                             related_name="confirmations")
    owner = EthereumAddressField()
    transaction_hash = Sha3HashField(null=True)  # Confirmation with signatures don't have transaction_hash
    confirmation_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in ConfirmationType])
    block_number = Uint256Field(null=True)
    block_date_time = models.DateTimeField(null=True)
    mined = models.BooleanField(default=False)
    signature = HexField(null=True, max_length=500)

    class Meta:
        unique_together = (('multisig_transaction', 'owner', 'confirmation_type'),)

    def __str__(self):
        mined = 'Mined' if self.mined else 'Pending'
        return '{} - {}'.format(self.safe, mined)

    def set_mined(self):
        self.mined = True
        return self.save()

    def is_execution(self):
        return ConfirmationType(self.confirmation_type) == ConfirmationType.EXECUTION

    def is_confirmation(self):
        return ConfirmationType(self.confirmation_type) == ConfirmationType.CONFIRMATION


class MonitoredAddressManager(models.Manager):
    def create_from_address(self, address: str, initial_block_number: int,
                            ethereum_tx: EthereumTx = None) -> 'MonitoredAddress':
        self.create(address=address,
                    ethereum_tx=ethereum_tx,
                    initial_block_number=initial_block_number,
                    tx_block_number=initial_block_number,
                    events_block_number=initial_block_number)

    def update_addresses(self, addresses: List[str], block_number: str, database_field: str) -> int:
        self.filter(address__int=addresses).update(**{database_field: block_number})


class MonitoredAddressQuerySet(models.QuerySet):
    def almost_updated(self, current_block_number: int, database_field: str,
                       confirmations: int, updated_blocks_behind: int):
        #TODO Use `__range`
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

    def __str__(self):
        return f'Address {self.address} - Initial-block-number={self.initial_block_number}' \
               f' - Tx-block-number={self.tx_block_number} - Events-block-number={self.events_block_number}'
