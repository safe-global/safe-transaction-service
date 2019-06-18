from enum import Enum

from django.db import models
from django.utils import timezone
from gnosis.eth.django.models import (EthereumAddressField, Sha3HashField,
                                      Uint256Field)
from gnosis.safe import SafeOperation
from model_utils.models import TimeStampedModel


class ConfirmationType(Enum):
    CONFIRMATION = 0
    EXECUTION = 1


class MultisigTransaction(TimeStampedModel):
    safe_tx_hash = Sha3HashField(primary_key=True)
    safe = EthereumAddressField()
    to = EthereumAddressField()
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
    transaction_hash = Sha3HashField(null=False, blank=False)
    confirmation_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in ConfirmationType])
    block_number = Uint256Field()
    block_date_time = models.DateTimeField()
    mined = models.BooleanField(default=False)

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
