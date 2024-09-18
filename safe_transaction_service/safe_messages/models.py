from logging import getLogger

from django.db import models
from django.db.models import JSONField

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel
from safe_eth.eth.django.models import (
    EthereumAddressBinaryField,
    HexV2Field,
    Keccak256Field,
)
from safe_eth.safe.safe_signature import SafeSignatureType

from safe_transaction_service.utils.constants import SIGNATURE_LENGTH

logger = getLogger(__name__)


class SafeMessage(TimeStampedModel):
    """
    Safe Message (EIP-191 or EIP-712) to build an EIP-1271 signature from
    """

    # Message hash is tied to Safe domain, so it's guaranteed to be unique
    message_hash = Keccak256Field(primary_key=True)
    safe = EthereumAddressBinaryField(db_index=True)
    message = JSONField()  # String if EIP191, object if EIP712
    proposed_by = EthereumAddressBinaryField()  # Owner proposing the message
    safe_app_id = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ["created"]

    def __str__(self):
        message_str = str(self.message)
        message_size = 15
        message = message_str[:message_size]
        if len(message_str) > message_size:
            message += "..."
        message_hash = HexBytes(self.message_hash).hex()
        return f"Safe Message {message_hash} - {message}"

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
    owner = EthereumAddressBinaryField(db_index=True)
    signature = HexV2Field(max_length=SIGNATURE_LENGTH)
    signature_type = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeSignatureType], db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["safe_message", "owner"],
                name="unique_safe_message_confirmation_owner",
            )
        ]
        ordering = ["created"]

    def __str__(self):
        return f"Safe Message Confirmation for owner {self.owner}"
