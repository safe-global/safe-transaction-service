import logging
from functools import cached_property
from typing import Optional

from django.db import models
from django.db.models import Index

from hexbytes import HexBytes

from gnosis.eth.account_abstraction import UserOperation as UserOperationClass
from gnosis.eth.account_abstraction import UserOperationMetadata
from gnosis.eth.django.models import (
    EthereumAddressV2Field,
    Keccak256Field,
    Uint256Field,
)
from gnosis.safe.account_abstraction import SafeOperation as SafeOperationClass

from safe_transaction_service.history import models as history_models

logger = logging.getLogger(__name__)


class UserOperation(models.Model):
    """
    EIP 4337 UserOperation

    https://www.erc4337.io/docs/understanding-ERC-4337/user-operation
    """

    hash = Keccak256Field(primary_key=True)
    ethereum_tx = models.ForeignKey(history_models.EthereumTx, on_delete=models.CASCADE)
    sender = EthereumAddressV2Field(db_index=True)
    nonce = Uint256Field()
    init_code = models.BinaryField(null=True, blank=True, editable=True)
    call_data = models.BinaryField(null=True, blank=True, editable=True)
    call_data_gas_limit = Uint256Field()
    verification_gas_limit = Uint256Field()
    pre_verification_gas = Uint256Field()
    max_fee_per_gas = Uint256Field()
    max_priority_fee_per_gas = Uint256Field()
    paymaster = EthereumAddressV2Field(
        db_index=True, null=True, blank=True, editable=True
    )
    paymaster_data = models.BinaryField(null=True, blank=True, editable=True)
    signature = models.BinaryField()
    entry_point = EthereumAddressV2Field(db_index=True)

    class Meta:
        unique_together = (("sender", "nonce"),)
        indexes = [
            Index(fields=["sender", "-nonce"]),
        ]

    def __str__(self):
        return f"UserOperation for {self.sender} with nonce {self.nonce}"

    @cached_property
    def paymaster_and_data(self) -> Optional[bytes]:
        if self.paymaster and self.paymaster_data:
            return HexBytes(self.paymaster) + HexBytes(self.paymaster_data)

    @cached_property
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

        return UserOperationClass(
            self.user_operation_hash,
            self.sender,
            self.nonce,
            bytes(self.init_code) if self.init_code else None,
            bytes(self.call_data) if self.call_data else None,
            self.call_data_gas_limit,
            self.verification_gas_limit,
            self.pre_verification_gas,
            self.max_fee_per_gas,
            self.max_priority_fee_per_gas,
            self.paymaster_and_data,
            self.signature,
            self.entry_point,
            user_operation_metadata,
        )

    def to_safe_operation(self):
        return SafeOperationClass.from_user_operation(self.to_user_operation())


class UserOperationReceipt(models.Model):
    user_operation = models.OneToOneField(UserOperation, on_delete=models.CASCADE)
    actual_gas_cost = Uint256Field()
    actual_gas_used = Uint256Field()
    success = models.BooleanField()
    reason = models.CharField(max_length=256)
    deposited = Uint256Field()


class SafeOperation(models.Model):
    hash = Keccak256Field(primary_key=True)  # safeOperationHash
    user_operation = models.ForeignKey(
        UserOperation, on_delete=models.CASCADE, null=True, blank=True
    )
    safe = EthereumAddressV2Field(db_index=True)
    nonce = Uint256Field()
    init_code_hash = Keccak256Field()
    call_data_hash = Keccak256Field()
    call_gas_limit = Uint256Field()
    verification_gas_limit = Uint256Field()
    pre_verification_gas = Uint256Field()
    max_fee_per_gas = Uint256Field()
    max_priority_fee_per_gas = Uint256Field()
    paymaster_and_data_hash = Keccak256Field()
    valid_after = models.DateTimeField()  # Epoch uint48
    valid_until = models.DateTimeField()  # Epoch uint48
