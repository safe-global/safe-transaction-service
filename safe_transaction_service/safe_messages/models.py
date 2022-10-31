from logging import getLogger

from django.db import models
from django.db.models import JSONField

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel

from gnosis.eth.django.models import EthereumAddressV2Field, HexField, Keccak256Field
from gnosis.safe.safe_signature import SafeSignatureType

logger = getLogger(__name__)


class SafeMessage(TimeStampedModel):
    """
    Safe Message (EIP-191 or EIP-712) to build an EIP-1271 signature from
    """

    safe = EthereumAddressV2Field(db_index=True)
    message_hash = Keccak256Field(db_index=True)
    message = JSONField()  # String if EIP191, object if EIP712
    proposed_by = EthereumAddressV2Field()  # Owner proposing the message
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = (("safe", "message_hash"),)
        ordering = ["created"]

    def __str__(self):
        return f"Safe Message {self.message_hash.hex()} - {self.description}"

    def build_signature(self) -> bytes:
        return b"".join(
            [
                HexBytes(signature)
                for _, signature in sorted(
                    self.confirmations.values_list("owner", "signature"),
                    key=lambda tup: tup[0].lower(),
                )
            ]
        )


class SafeMessageConfirmation(TimeStampedModel):
    """
    Owner signature for a Safe Message
    """

    safe_message = models.ForeignKey(
        SafeMessage,
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="confirmations",
    )
    owner = EthereumAddressV2Field()
    signature = HexField(max_length=5000)
    signature_type = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeSignatureType], db_index=True
    )

    class Meta:
        unique_together = (("safe_message", "owner"),)
        ordering = ["created"]

    def __str__(self):
        return f"Safe Message Confirmation for owner {self.owner}"
