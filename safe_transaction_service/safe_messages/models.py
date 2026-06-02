# SPDX-License-Identifier: FSL-1.1-MIT
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
from safe_eth.safe.safe_signature import (
    SafeSignature,
    SafeSignatureContract,
    SafeSignatureType,
)
from safe_eth.util.util import to_0x_hex_str

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
    origin = models.JSONField(default=dict)  # To store arbitrary data

    class Meta:
        ordering = ["created"]

    def __str__(self):
        message_str = str(self.message)
        message_size = 15
        message = message_str[:message_size]
        if len(message_str) > message_size:
            message += "..."
        message_hash = to_0x_hex_str(HexBytes(self.message_hash))
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

    def build_eip1271_signature(self) -> bytes:
        """
        Build a single EIP-1271 signature claiming ``self.safe`` as signer, with the inner
        multi-owner blob assembled in the format expected by Safe's ``checkSignatures``
        (statics first, dynamics last with cumulative offsets).

        Unlike ``build_signature``, which naively concatenates per-owner confirmations and
        works only when every confirmation is an EOA signature, this produces a blob that is
        directly usable wherever a single ``SafeSignature`` signed by this Safe is expected
        (e.g. as the ``signature`` body for ``/api/v2/delegates/`` when the delegator is a
        Safe). The consumer does not need to wrap or rewrite offsets.

        :return: Wrapped ``CONTRACT_SIGNATURE`` bytes (``v=0 | r=safe | s=65 | length | inner``)
            or ``b""`` if there are no parseable confirmations yet.
        """
        message_hash = HexBytes(self.message_hash)
        parsed_signatures: list[SafeSignature] = []
        for confirmation in self.confirmations.all():
            parsed = SafeSignature.parse_signature(
                bytes(confirmation.signature), message_hash
            )
            if len(parsed) != 1:
                logger.warning(
                    "SafeMessage=%s confirmation for owner=%s parsed into %d signatures; skipping",
                    to_0x_hex_str(message_hash),
                    confirmation.owner,
                    len(parsed),
                )
                continue
            parsed_signatures.append(parsed[0])

        if not parsed_signatures:
            return b""

        # `export_signatures` (plural) sorts by owner.lower() and rewrites the contract
        # signature offsets so the resulting blob satisfies GS020-GS023 of `checkSignatures`.
        inner_blob = SafeSignature.export_signatures(parsed_signatures)

        # `safe_hash`/`safe_hash_preimage` are metadata kept on the object for `is_valid()`
        # and do not appear in the exported bytes, so the stored message_hash is enough.
        outer = SafeSignatureContract.from_values(
            safe_owner=self.safe,
            safe_hash=message_hash,
            safe_hash_preimage=message_hash,
            contract_signature=inner_blob,
        )
        return bytes(outer.export_signature())


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
