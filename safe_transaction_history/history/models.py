from enum import Enum

from django.db import models
from django.utils import timezone

from gnosis.eth.django.models import EthereumAddressField, Sha3HashField, Uint256Field
from model_utils.models import TimeStampedModel


class HistoryOperation(Enum):
    CONFIRMATION = 0
    EXECUTION = 1


class MultisigTransaction(TimeStampedModel):
    safe = EthereumAddressField()
    to = EthereumAddressField()
    value = Uint256Field()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField()
    safe_tx_gas = Uint256Field()
    data_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressField(null=True)
    refund_receiver = EthereumAddressField(null=True)
    nonce = Uint256Field()
    mined = models.BooleanField(default=False)  # True if transaction executed, 0 otherwise
    # Defines when a multisig transaction gets executed (confirmations included)
    execution_date = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        executed = 'Executed' if self.mined else 'Pending'
        return '{} - {}'.format(self.safe, executed)

    def set_mined(self):
        self.mined = True
        self.execution_date = timezone.now()
        self.save(update_fields=['mined', 'execution_date'])

        # Mark every confirmation as mined
        MultisigConfirmation.objects.filter(multisig_transaction=self).update(mined=True)


class MultisigConfirmation(TimeStampedModel):
    owner = EthereumAddressField()
    contract_transaction_hash = Sha3HashField(null=False, blank=False)
    transaction_hash = Sha3HashField(null=False, blank=False)
    type = models.PositiveSmallIntegerField(null=False, blank=False)
    block_number = models.BigIntegerField()
    block_date_time = models.DateTimeField()
    mined = models.BooleanField(default=False)
    multisig_transaction = models.ForeignKey(MultisigTransaction,
                                             on_delete=models.CASCADE,
                                             related_name="confirmations")

    def __str__(self):
        mined = 'Mined' if self.mined else 'Pending'
        return '{} - {}'.format(self.safe, mined)

    def set_mined(self):
        self.mined = True
        return self.save()

    def is_execution(self):
        return HistoryOperation(self.type) == HistoryOperation.EXECUTION

    def is_confirmation(self):
        return HistoryOperation(self.type) == HistoryOperation.CONFIRMATION
