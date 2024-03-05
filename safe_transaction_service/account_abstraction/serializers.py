from typing import List

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

import gnosis.eth.django.serializers as eth_serializers
from gnosis.eth import EthereumClientProvider
from gnosis.eth.utils import fast_keccak
from gnosis.safe.account_abstraction import SafeOperation as SafeOperationClass
from gnosis.safe.safe_signature import SafeSignature

from safe_transaction_service.utils.ethereum import get_chain_id

from ..utils.serializers import get_safe_owners
from .models import SafeOperation

SIGNATURE_LENGTH = 5_000


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeOperationSerializer(serializers.Serializer):
    safe = eth_serializers.EthereumAddressField()
    nonce = serializers.IntegerField(min_value=0)
    init_code = eth_serializers.HexadecimalField(allow_null=True)
    call_data = eth_serializers.HexadecimalField(allow_null=True)
    call_data_gas_limit = serializers.IntegerField(min_value=0)
    verification_gas_limit = serializers.IntegerField(min_value=0)
    pre_verification_gas = serializers.IntegerField(min_value=0)
    max_fee_per_gas = serializers.IntegerField(min_value=0)
    max_priority_fee_per_gas = serializers.IntegerField(min_value=0)
    paymaster = eth_serializers.EthereumAddressField(allow_null=True)
    paymaster_data = eth_serializers.HexadecimalField(allow_null=True)
    signature = eth_serializers.HexadecimalField(
        min_length=65, max_length=SIGNATURE_LENGTH
    )
    entry_point = eth_serializers.EthereumAddressField()

    valid_after = serializers.IntegerField(min_value=0)  # Epoch uint48
    valid_until = serializers.IntegerField(min_value=0)  # Epoch uint48

    safe_module_address = eth_serializers.EthereumAddressField()

    def _validate_signature(
        self,
        safe_address: ChecksumAddress,
        safe_operation_hash: bytes,
        safe_operation_hash_preimage: bytes,
        signature: bytes,
    ) -> List[SafeSignature]:
        safe_owners = get_safe_owners(safe_address)
        parsed_signatures = SafeSignature.parse_signature(
            signature, safe_operation_hash, safe_operation_hash_preimage
        )
        signature_owners = {}
        safe_signatures = []
        ethereum_client = EthereumClientProvider()
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if owner not in safe_owners:
                raise ValidationError(
                    f"Signer={owner} is not an owner. Current owners={safe_owners}"
                )
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={safe_signature.signature.hex()} for owner={owner} is not valid"
                )
            if owner in signature_owners:
                raise ValidationError(f"Signature for owner={owner} is duplicated")

            signature_owners.append(owner)
            safe_signatures.append(safe_signature)
        return signature

    def validate(self, attrs):
        safe_module_address = attrs["safe_module_address"]
        # TODO Check safe_module_address is whitelisted
        # if module_address IN

        valid_after = attrs["valid_after"]
        valid_until = attrs["valid_until"]

        if valid_after > valid_until:
            raise ValidationError("`valid_after` cannot be higher than `valid_until`")

        safe_address = attrs["safe"]
        paymaster = attrs["paymaster"]
        paymaster_data = attrs["paymaster_data"]
        paymaster_and_data = (
            (HexBytes(paymaster) + HexBytes(paymaster_data))
            if paymaster and paymaster_data
            else None
        )

        safe_operation = SafeOperationClass(
            attrs["safe"],
            attrs["nonce"],
            fast_keccak(attrs["init_code"]),
            fast_keccak(attrs["call_data"]),
            attrs["call_data_gas_limit"],
            attrs["verification_gas_limit"],
            attrs["pre_verification_gas"],
            attrs["max_fee_per_gas"],
            attrs["max_priority_fee_per_gas"],
            fast_keccak(paymaster_and_data),
            valid_after,
            valid_until,
            attrs["entry_point"],
            attrs["signature"],
        )

        chain_id = get_chain_id()
        safe_operation_hash = safe_operation.get_safe_operation_hash(
            chain_id, safe_module_address
        )

        if SafeOperation.objects.filter(hash=safe_operation_hash).exists():
            raise ValidationError(
                f"SafeOperation with hash={safe_operation_hash} already exists"
            )

        safe_signatures = self._validate_signature(
            safe_address,
            safe_operation_hash,
            safe_operation.get_safe_operation_hash_preimage(
                chain_id, safe_module_address
            ),
            attrs["signature"],
        )
        if not safe_signatures:
            raise ValidationError("No valid signatures provided")

        attrs["safe_operation_hash"] = safe_operation_hash
        attrs["safe_signatures"] = safe_signatures
        return attrs

    def save(self, **kwargs):
        safe_operation_hash = self.validated_data["safe_operation_hash"]

        safe_operation_confirmations = []
        safe_signatures = self.validated_data["safe_signatures"]
        for safe_signature in safe_signatures:
            """
            multisig_confirmation, _ = SafeOperationConfirmation.objects.get_or_create(
                multisig_transaction_hash=safe_tx_hash,
                owner=safe_signature.owner,
                defaults={
                    "multisig_transaction_id": safe_tx_hash,
                    "signature": safe_signature.export_signature(),
                    "signature_type": safe_signature.signature_type.value,
                },
            )
            safe_operation_confirmations.append(multisig_confirmation)
            """
            pass

        return safe_operation_confirmations
