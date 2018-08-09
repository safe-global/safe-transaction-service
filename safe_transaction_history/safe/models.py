from django.db import models
from django_eth.models import EthereumAddressField
from model_utils.models import TimeStampedModel


class MultisigTransaction(TimeStampedModel):
    safe = EthereumAddressField()
    to = EthereumAddressField()
    value = models.BigIntegerField()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField()
    nonce = models.BigIntegerField()
    status = models.BooleanField(default=False)  # True if transaction executed, 0 otherwise
    # Defines when a multisig transaction gets executed (confirmations included)
    execution_date = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.safe


class MultisigConfirmation(TimeStampedModel):
    owner = EthereumAddressField()
    contract_transaction_hash = models.CharField(max_length=66, null=False, blank=False)
    transaction_hash = models.CharField(max_length=66, null=False, blank=False)
    type = models.CharField(max_length=20, null=False, blank=False)
    block_number = models.IntegerField()
    block_date_time = models.DateTimeField()
    status = models.BooleanField(
        default=False
    )  # True if transaction mined and executed successfully, 0 otherwise
    multisig_transaction = models.ForeignKey(MultisigTransaction,
                                             on_delete=models.CASCADE,
                                             related_name="confirmations")

    def __str__(self):
        return self.owner
