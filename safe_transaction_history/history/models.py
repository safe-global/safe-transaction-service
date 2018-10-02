from django.db import models
from django.utils import timezone
from django_eth.models import EthereumAddressField, Sha3HashField, Uint256Field
from model_utils.models import TimeStampedModel


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

    class Meta:
        unique_together = (('safe', 'nonce'),)

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
    type = models.CharField(max_length=20, null=False, blank=False)
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

    # FIXME Use enum for confirmation/execution
    def is_execution(self):
        return self.type == 'execution'

    def is_confirmation(self):
        return self.type == 'confirmation'
