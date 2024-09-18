import logging
from functools import cached_property
from typing import Optional

from django.db import models
from django.db.models import Index

from eth_abi.packed import encode_packed
from hexbytes import HexBytes
from model_utils.models import TimeStampedModel
from safe_eth.eth.account_abstraction import UserOperation as UserOperationClass
from safe_eth.eth.account_abstraction import UserOperationMetadata
from safe_eth.eth.django.models import (
    EthereumAddressBinaryField,
    HexV2Field,
    Keccak256Field,
    Uint256Field,
)
from safe_eth.safe.account_abstraction import SafeOperation as SafeOperationClass
from safe_eth.safe.safe_signature import SafeSignatureType

from safe_transaction_service.history import models as history_models
from safe_transaction_service.utils.constants import SIGNATURE_LENGTH

logger = logging.getLogger(__name__)


class UserOperation(models.Model):
    """
    EIP 4337 UserOperation

    https://www.erc4337.io/docs/understanding-ERC-4337/user-operation
    """

    hash = Keccak256Field(primary_key=True)
    ethereum_tx = models.ForeignKey(
        history_models.EthereumTx, on_delete=models.CASCADE, null=True, blank=True
    )
    sender = EthereumAddressBinaryField(db_index=True)
    nonce = Uint256Field()
    init_code = models.BinaryField(null=True, blank=True, editable=True)
    call_data = models.BinaryField(null=True, blank=True, editable=True)
    call_gas_limit = Uint256Field()
    verification_gas_limit = Uint256Field()
    pre_verification_gas = Uint256Field()
    max_fee_per_gas = Uint256Field()
    max_priority_fee_per_gas = Uint256Field()
    paymaster = EthereumAddressBinaryField(
        db_index=True, null=True, blank=True, editable=True
    )
    paymaster_data = models.BinaryField(null=True, blank=True, editable=True)
    signature = models.BinaryField(null=True, blank=True, editable=True)
    entry_point = EthereumAddressBinaryField(db_index=True)

    class Meta:
        indexes = [
            Index(fields=["sender", "-nonce"]),
        ]

    def __str__(self) -> str:
        return f"{HexBytes(self.hash).hex()} UserOperation for sender={self.sender} with nonce={self.nonce}"

    @cached_property
    def paymaster_and_data(self) -> Optional[HexBytes]:
        if self.paymaster and self.paymaster_data:
            return HexBytes(HexBytes(self.paymaster) + HexBytes(self.paymaster_data))

    def to_user_operation(self, add_tx_metadata: bool = False) -> UserOperationClass:
        """
        Returns a safe-eth-py UserOperation object

        :param add_tx_metadata: If `True` more database queries will be performed to get the transaction metadata
        :return: safe-eth-py `UserOperation`
        """
        user_operation_metadata = (
            UserOperationMetadata(
                # More DB queries
                transaction_hash=HexBytes(self.ethereum_tx_id),
                block_hash=HexBytes(self.ethereum_tx.block.block_hash),
                block_number=self.ethereum_tx.block.number,
            )
            if add_tx_metadata
            else None
        )

        if not self.signature:
            raise ValueError("Signature should not be empty")
        signature = HexBytes(self.signature)

        return UserOperationClass(
            HexBytes(self.hash),
            self.sender,
            self.nonce,
            HexBytes(self.init_code) if self.init_code else b"",
            HexBytes(self.call_data) if self.call_data else b"",
            self.call_gas_limit,
            self.verification_gas_limit,
            self.pre_verification_gas,
            self.max_fee_per_gas,
            self.max_priority_fee_per_gas,
            self.paymaster_and_data if self.paymaster_and_data else b"",
            signature,
            self.entry_point,
            user_operation_metadata,
        )

    def to_safe_operation(self) -> SafeOperationClass:
        """
        :return: SafeOperation built from UserOperation
        :raises: ValueError
        """
        return SafeOperationClass.from_user_operation(self.to_user_operation())


class UserOperationReceipt(models.Model):
    user_operation = models.OneToOneField(
        UserOperation, on_delete=models.CASCADE, related_name="receipt"
    )
    actual_gas_cost = Uint256Field()
    actual_gas_used = Uint256Field()
    success = models.BooleanField()
    reason = models.CharField(max_length=256, blank=True)
    deposited = Uint256Field()

    def __str__(self) -> str:
        return f"{HexBytes(self.user_operation_id).hex()} UserOperationReceipt"


class SafeOperation(TimeStampedModel):
    hash = Keccak256Field(primary_key=True)  # safeOperationHash
    user_operation = models.OneToOneField(
        UserOperation, on_delete=models.CASCADE, related_name="safe_operation"
    )
    valid_after = models.DateTimeField(null=True)  # Epoch uint48
    valid_until = models.DateTimeField(null=True)  # Epoch uint48
    module_address = EthereumAddressBinaryField(db_index=True)

    def __str__(self) -> str:
        return f"{HexBytes(self.hash).hex()} SafeOperation for user-operation={HexBytes(self.user_operation_id).hex()}"

    def build_signature_prefix(self) -> bytes:
        """
        `UserOperation` `signature` is used to store data for the `SafeOperation`
        First 6 bytes of the signature are `SafeOperation` `valid_after` and next 6 are `valid_until`
        Real user signature is after those 12 bytes

        :return: 12 bytes of `valid` encoded
        """
        return encode_packed(
            ["uint48"] * 2,
            [
                int(valid_date.timestamp()) if valid_date else 0
                for valid_date in (
                    self.valid_after,
                    self.valid_until,
                )
            ],
        )

    def build_signature(self) -> bytes:
        """
        `UserOperation` `signature` is used to store data for the `SafeOperation`
        First 6 bytes of the signature are `SafeOperation` `valid_after` and next 6 are `valid_until`
        Real user signature is after those 12 bytes

        :return: 12 bytes of `valid` encoded following by the signature built from the confirmations
        """
        valid_encoded = self.build_signature_prefix()
        confirmations_signature = b"".join(
            [
                HexBytes(signature)
                for _, signature in sorted(
                    self.confirmations.values_list("owner", "signature"),
                    key=lambda tup: tup[0].lower(),
                )
            ]
        )
        return valid_encoded + confirmations_signature


class SafeOperationConfirmation(TimeStampedModel):
    safe_operation = models.ForeignKey(
        SafeOperation,
        on_delete=models.CASCADE,
        related_name="confirmations",
    )
    owner = EthereumAddressBinaryField()
    signature = HexV2Field(null=True, default=None, max_length=SIGNATURE_LENGTH)
    signature_type = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeSignatureType], db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["safe_operation", "owner"],
                name="unique_safe_operation_owner_confirmation",
            )
        ]
        ordering = ["created"]

    def __str__(self):
        return (
            f"Safe Operation Confirmation of owner={self.owner} for "
            f"safe-operation={HexBytes(self.safe_operation_id).hex()}"
        )
