from django.db import models
from model_utils.models import TimeStampedModel
import ethereum.utils

from .validators import validate_checksumed_address


# =========================================
#                  Fields
# =========================================

class EthereumAddressField(models.CharField):
    default_validators = [validate_checksumed_address]
    description = "Ethereum address"

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 42
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs['max_length']
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        value = super().to_python(value)
        if value:
            return ethereum.utils.checksum_encode(value)
        else:
            return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value:
            return ethereum.utils.checksum_encode(value)
        else:
            return value


# =========================================
#                  Models
# =========================================

class MultisigTransaction(TimeStampedModel):
    safe = EthereumAddressField()
    to = EthereumAddressField()
    value = models.BigIntegerField()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField()
    nonce = models.PositiveIntegerField()
    status = models.BooleanField(default=False) # True if transaction executed, 0 otherwise

    def __str__(self):
        return self.safe


class MultisigConfirmation(TimeStampedModel):
    owner = EthereumAddressField()
    contract_transaction_hash = models.CharField(max_length=66, null=False, blank=False)
    transaction_hash = models.CharField(max_length=66, null=False, blank=False)
    block_number = models.IntegerField()
    block_date_time = models.DateTimeField()
    status = models.BooleanField(
        default=False
    ) # True if transaction mined and executed successfully, 0 otherwise
    multisig_transaction = models.ForeignKey(MultisigTransaction, on_delete=models.CASCADE, related_name="confirmations")

    def __str__(self):
        return self.owner