from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from eth_typing import ChecksumAddress, HexStr
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

import gnosis.eth.django.serializers as eth_serializers
from gnosis.eth import EthereumClientProvider
from gnosis.eth.account_abstraction import UserOperation as UserOperationClass
from gnosis.eth.utils import fast_keccak
from gnosis.safe.account_abstraction import SafeOperation as SafeOperationClass
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.utils.constants import SIGNATURE_LENGTH
from safe_transaction_service.utils.ethereum import get_chain_id

from ..utils.serializers import get_safe_owners
from .models import SafeOperation
from .models import SafeOperation as SafeOperationModel
from .models import SafeOperationConfirmation
from .models import UserOperation as UserOperationModel


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeOperationSerializer(serializers.Serializer):
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
    # Safe Operation fields
    valid_after = serializers.DateTimeField(allow_null=True)  # Epoch uint48
    valid_until = serializers.DateTimeField(allow_null=True)  # Epoch uint48
    module_address = eth_serializers.EthereumAddressField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ethereum_client = EthereumClientProvider()

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
        owners_processed = set()
        safe_signatures = []
        for safe_signature in parsed_signatures:
            owner = safe_signature.owner
            if owner not in safe_owners:
                raise ValidationError(
                    f"Signer={owner} is not an owner. Current owners={safe_owners}. "
                    f"Safe-operation-hash={safe_operation_hash.hex()}"
                )
            if not safe_signature.is_valid(self.ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={safe_signature.signature.hex()} for owner={owner} is not valid"
                )
            if owner in owners_processed:
                raise ValidationError(f"Signature for owner={owner} is duplicated")

            owners_processed.add(owner)
            safe_signatures.append(safe_signature)
        return safe_signatures

    def validate_init_code(self, init_code: Optional[HexBytes]) -> Optional[HexBytes]:
        """
        Check `init_code` is not provided for already initialized contracts

        :param init_code:
        :return: `init_code`
        """
        if init_code:
            safe_address = self.context["safe_address"]
            if self.ethereum_client.is_contract(safe_address):
                raise ValidationError(
                    "`init_code` must be empty as the contract was already initialized"
                )
        return init_code

    def validate_nonce(self, nonce: int) -> int:
        """
        Check nonce is higher than the last executed SafeOperation

        :param nonce:
        :return: `nonce`
        """
        safe_address = self.context["safe_address"]
        if (
            UserOperationModel.objects.filter(sender=safe_address, nonce__gte=nonce)
            .exclude(ethereum_tx=None)
            .exists()
        ):
            raise ValidationError(f"Nonce={nonce} too low for safe={safe_address}")
        return nonce

    def validate_valid_until(self, valid_until: Optional[int]) -> Optional[int]:
        """
        Make sure ``valid_until`` is not previous to the current timestamp, so it will be valid for some time
        :param valid_until:
        :return: `valid_until`
        """
        if valid_until and valid_until <= timezone.now():
            raise ValidationError(
                "`valid_until` cannot be previous to the current timestamp"
            )
        return valid_until

    def validate(self, attrs):
        attrs = super().validate(attrs)

        module_address = attrs["module_address"]
        # TODO Check module_address is whitelisted
        if module_address not in settings.ETHEREUM_4337_SUPPORTED_SAFE_MODULES:
            raise ValidationError(
                f"Module-address={module_address} not supported, "
                f"valid values are {settings.ETHEREUM_4337_SUPPORTED_SAFE_MODULES}"
            )

        valid_after = attrs["valid_after"] or 0
        valid_until = attrs["valid_until"] or 0
        if valid_after and valid_until and valid_after > valid_until:
            raise ValidationError("`valid_after` cannot be higher than `valid_until`")

        safe_address = self.context["safe_address"]
        # FIXME Check all these `None`
        paymaster = attrs["paymaster"] or b""
        paymaster_data = attrs["paymaster_data"] or b""
        attrs["paymaster_and_data"] = bytes(paymaster) + bytes(paymaster_data)

        safe_operation = SafeOperationClass(
            safe_address,
            attrs["nonce"],
            fast_keccak(attrs["init_code"] or b""),
            fast_keccak(attrs["call_data"] or b""),
            attrs["call_data_gas_limit"],
            attrs["verification_gas_limit"],
            attrs["pre_verification_gas"],
            attrs["max_fee_per_gas"],
            attrs["max_priority_fee_per_gas"],
            fast_keccak(attrs["paymaster_and_data"]),
            valid_after,
            valid_until,
            attrs["entry_point"],
            attrs["signature"],
        )

        chain_id = get_chain_id()
        attrs["chain_id"] = chain_id
        safe_operation_hash = safe_operation.get_safe_operation_hash(
            chain_id, module_address
        )

        if SafeOperationModel.objects.filter(hash=safe_operation_hash).exists():
            raise ValidationError(
                f"SafeOperation with hash={safe_operation_hash.hex()} already exists"
            )

        safe_signatures = self._validate_signature(
            safe_address,
            safe_operation_hash,
            safe_operation.safe_operation_hash_preimage,
            attrs["signature"],
        )
        if not safe_signatures:
            raise ValidationError("At least one signature must be provided")

        attrs["safe_operation_hash"] = safe_operation_hash
        attrs["safe_signatures"] = safe_signatures
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        user_operation = UserOperationClass(
            b"",
            self.context["safe_address"],
            self.validated_data["nonce"],
            self.validated_data["init_code"],
            self.validated_data["call_data"],
            self.validated_data["call_data_gas_limit"],
            self.validated_data["verification_gas_limit"],
            self.validated_data["pre_verification_gas"],
            self.validated_data["max_fee_per_gas"],
            self.validated_data["max_priority_fee_per_gas"],
            self.validated_data["paymaster_and_data"],
            self.validated_data["signature"],
            self.validated_data["entry_point"],
        )

        user_operation_hash = user_operation.calculate_user_operation_hash(
            self.validated_data["chain_id"]
        )

        user_operation_model, created = UserOperationModel.objects.get_or_create(
            hash=user_operation_hash,
            defaults={
                "ethereum_tx": None,
                "sender": user_operation.sender,
                "nonce": user_operation.nonce,
                "init_code": user_operation.init_code,
                "call_data": user_operation.call_data,
                "call_data_gas_limit": user_operation.call_gas_limit,
                "verification_gas_limit": user_operation.verification_gas_limit,
                "pre_verification_gas": user_operation.pre_verification_gas,
                "max_fee_per_gas": user_operation.max_fee_per_gas,
                "max_priority_fee_per_gas": user_operation.max_priority_fee_per_gas,
                "paymaster": user_operation.paymaster,
                "paymaster_data": user_operation.paymaster_data,
                "signature": user_operation.signature,
                "entry_point": user_operation.entry_point,
            },
        )

        if created:
            safe_operation_model = SafeOperationModel.objects.create(
                hash=self.validated_data["safe_operation_hash"],
                user_operation=user_operation_model,
                valid_after=self.validated_data["valid_after"],
                valid_until=self.validated_data["valid_until"],
                module_address=self.validated_data["module_address"],
            )

        safe_signatures = self.validated_data["safe_signatures"]
        for safe_signature in safe_signatures:
            SafeOperationConfirmation.objects.get_or_create(
                safe_operation=safe_operation_model,
                owner=safe_signature.owner,
                defaults={
                    "signature": safe_signature.export_signature(),
                    "signature_type": safe_signature.signature_type.value,
                },
            )

        return user_operation_model


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeOperationConfirmationResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    modified = serializers.DateTimeField()
    owner = eth_serializers.EthereumAddressField()
    signature = eth_serializers.HexadecimalField()
    signature_type = serializers.SerializerMethodField()

    def get_signature_type(self, obj: SafeOperationConfirmation) -> str:
        return SafeSignatureType(obj.signature_type).name


class SafeOperationResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    modified = serializers.DateTimeField()
    ethereum_tx_hash = eth_serializers.HexadecimalField(
        source="user_operation.ethereum_tx_id"
    )

    # User Operation fields
    sender = eth_serializers.EthereumAddressField(source="user_operation.sender")
    user_operation_hash = eth_serializers.HexadecimalField(source="user_operation.hash")
    safe_operation_hash = eth_serializers.HexadecimalField(source="hash")
    nonce = serializers.IntegerField(min_value=0, source="user_operation.nonce")
    init_code = eth_serializers.HexadecimalField(
        allow_null=True, source="user_operation.init_code"
    )
    call_data = eth_serializers.HexadecimalField(
        allow_null=True, source="user_operation.call_data"
    )
    call_data_gas_limit = serializers.IntegerField(
        min_value=0, source="user_operation.call_data_gas_limit"
    )
    verification_gas_limit = serializers.IntegerField(
        min_value=0, source="user_operation.verification_gas_limit"
    )
    pre_verification_gas = serializers.IntegerField(
        min_value=0, source="user_operation.pre_verification_gas"
    )
    max_fee_per_gas = serializers.IntegerField(
        min_value=0, source="user_operation.max_fee_per_gas"
    )
    max_priority_fee_per_gas = serializers.IntegerField(
        min_value=0, source="user_operation.max_priority_fee_per_gas"
    )
    paymaster = eth_serializers.EthereumAddressField(
        allow_null=True, source="user_operation.paymaster"
    )
    paymaster_data = eth_serializers.HexadecimalField(
        allow_null=True, source="user_operation.paymaster_data"
    )
    signature = eth_serializers.HexadecimalField(source="user_operation.signature")
    entry_point = eth_serializers.EthereumAddressField(
        source="user_operation.entry_point"
    )

    # Safe Operation fields
    valid_after = serializers.DateTimeField()
    valid_until = serializers.DateTimeField()
    module_address = eth_serializers.EthereumAddressField()

    confirmations = serializers.SerializerMethodField()
    prepared_signature = serializers.SerializerMethodField()

    def get_confirmations(self, obj: SafeOperation) -> Dict[str, Any]:
        """
        Filters confirmations queryset

        :param obj: SafeOperation instance
        :return: Serialized queryset
        """
        return SafeOperationConfirmationResponseSerializer(
            obj.confirmations, many=True
        ).data

    def get_prepared_signature(self, obj: SafeOperation) -> Optional[HexStr]:
        """
        Prepared signature sorted

        :param obj: SafeOperation instance
        :return: Serialized queryset
        """
        signature = HexBytes(obj.build_signature())
        return signature.hex() if signature else None
