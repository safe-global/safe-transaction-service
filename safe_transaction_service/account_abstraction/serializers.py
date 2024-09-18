import datetime
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import safe_eth.eth.django.serializers as eth_serializers
from eth_typing import ChecksumAddress, HexStr
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from safe_eth.eth import get_auto_ethereum_client
from safe_eth.eth.account_abstraction import UserOperation as UserOperationClass
from safe_eth.eth.utils import fast_keccak, fast_to_checksum_address
from safe_eth.safe.account_abstraction import SafeOperation as SafeOperationClass
from safe_eth.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.utils.constants import SIGNATURE_LENGTH
from safe_transaction_service.utils.ethereum import get_chain_id

from ..utils.serializers import get_safe_owners
from .helpers import decode_init_code
from .models import SafeOperation as SafeOperationModel
from .models import SafeOperationConfirmation
from .models import UserOperation as UserOperationModel


# ================================================ #
#            Request Serializers
# ================================================ #
class SafeOperationSignatureValidatorMixin:
    """
    Mixin class to validate SafeOperation signatures. `_get_owners` can be overridden to define
    the valid owners to sign
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ethereum_client = get_auto_ethereum_client()
        self._deployment_owners: List[ChecksumAddress] = []

    def _get_owners(self, safe_address: ChecksumAddress) -> List[ChecksumAddress]:
        """
        :param safe_address:
        :return:  `init_code` decoded owners if Safe is not deployed or current blockchain owners if Safe is deployed
        """
        try:
            return get_safe_owners(safe_address)
        except ValidationError as exc:
            if self._deployment_owners:
                return self._deployment_owners
            raise exc

    def _validate_signature(
        self,
        safe_address: ChecksumAddress,
        safe_operation_hash: bytes,
        safe_operation_hash_preimage: bytes,
        signature: bytes,
    ) -> List[SafeSignature]:
        safe_owners = self._get_owners(safe_address)
        parsed_signatures = SafeSignature.parse_signature(
            signature,
            safe_operation_hash,
            safe_hash_preimage=safe_operation_hash_preimage,
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


class SafeOperationSerializer(
    SafeOperationSignatureValidatorMixin, serializers.Serializer
):
    nonce = serializers.IntegerField(min_value=0)
    init_code = eth_serializers.HexadecimalField(allow_null=True)
    call_data = eth_serializers.HexadecimalField(allow_null=True)
    call_gas_limit = serializers.IntegerField(min_value=0)
    verification_gas_limit = serializers.IntegerField(min_value=0)
    pre_verification_gas = serializers.IntegerField(min_value=0)
    max_fee_per_gas = serializers.IntegerField(min_value=0)
    max_priority_fee_per_gas = serializers.IntegerField(min_value=0)
    paymaster_and_data = eth_serializers.HexadecimalField(allow_null=True)
    signature = eth_serializers.HexadecimalField(
        min_length=65, max_length=SIGNATURE_LENGTH
    )
    entry_point = eth_serializers.EthereumAddressField()
    # Safe Operation fields
    valid_after = serializers.DateTimeField(allow_null=True)  # Epoch uint48
    valid_until = serializers.DateTimeField(allow_null=True)  # Epoch uint48
    module_address = eth_serializers.EthereumAddressField()

    def validate_init_code(self, init_code: Optional[HexBytes]) -> Optional[HexBytes]:
        """
        Check `init_code` is not provided for already initialized contracts

        :param init_code:
        :return: `init_code`
        """
        safe_address = self.context["safe_address"]
        safe_is_deployed = self.ethereum_client.is_contract(safe_address)
        if init_code:
            if safe_is_deployed:
                raise ValidationError(
                    "`init_code` must be empty as the contract was already initialized"
                )

            try:
                decoded_init_code = decode_init_code(init_code, self.ethereum_client)
            except ValueError:
                raise ValidationError("Cannot decode data")
            if not self.ethereum_client.is_contract(decoded_init_code.factory_address):
                raise ValidationError(
                    f"`init_code` factory-address={decoded_init_code.factory_address} is not initialized"
                )

            if decoded_init_code.expected_address != safe_address:
                raise ValidationError(
                    f"Provided safe-address={safe_address} does not match "
                    f"calculated-safe-address={decoded_init_code.expected_address}"
                )
            # Store owners used for deployment, to do checks afterward
            self._deployment_owners = decoded_init_code.owners
        elif not safe_is_deployed:
            raise ValidationError(
                "`init_code` was not provided and contract was not initialized"
            )

        return init_code

    def validate_module_address(
        self, module_address: ChecksumAddress
    ) -> ChecksumAddress:
        if module_address not in settings.ETHEREUM_4337_SUPPORTED_SAFE_MODULES:
            raise ValidationError(
                f"Module-address={module_address} not supported, "
                f"valid values are {settings.ETHEREUM_4337_SUPPORTED_SAFE_MODULES}"
            )
        return module_address

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

    def validate_paymaster_and_data(
        self, paymaster_and_data: Optional[HexBytes]
    ) -> Optional[HexBytes]:
        if paymaster_and_data:
            if len(paymaster_and_data) < 20:
                raise ValidationError(
                    "`paymaster_and_data` length should be at least 20 bytes"
                )

            paymaster_address = fast_to_checksum_address(paymaster_and_data[:20])
            if not self.ethereum_client.is_contract(paymaster_address):
                raise ValidationError(
                    f"paymaster={paymaster_address} was not found in blockchain"
                )

        return paymaster_and_data

    def validate_valid_until(
        self, valid_until: Optional[datetime.datetime]
    ) -> Optional[datetime.datetime]:
        """
        Make sure ``valid_until`` is not previous to the current timestamp

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

        valid_after, valid_until = [
            int(attrs[key].timestamp()) if attrs[key] else 0
            for key in ("valid_after", "valid_until")
        ]
        if valid_after and valid_until and valid_after > valid_until:
            raise ValidationError("`valid_after` cannot be higher than `valid_until`")

        safe_address = self.context["safe_address"]
        safe_operation = SafeOperationClass(
            safe_address,
            attrs["nonce"],
            fast_keccak(attrs["init_code"] or b""),
            fast_keccak(attrs["call_data"] or b""),
            attrs["call_gas_limit"],
            attrs["verification_gas_limit"],
            attrs["pre_verification_gas"],
            attrs["max_fee_per_gas"],
            attrs["max_priority_fee_per_gas"],
            fast_keccak(attrs["paymaster_and_data"] or b""),
            valid_after,
            valid_until,
            attrs["entry_point"],
            attrs["signature"],
        )

        module_address = attrs["module_address"]
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
            b"",  # Hash will be calculated later
            self.context["safe_address"],
            self.validated_data["nonce"],
            self.validated_data["init_code"] or b"",
            self.validated_data["call_data"] or b"",
            self.validated_data["call_gas_limit"],
            self.validated_data["verification_gas_limit"],
            self.validated_data["pre_verification_gas"],
            self.validated_data["max_fee_per_gas"],
            self.validated_data["max_priority_fee_per_gas"],
            self.validated_data["paymaster_and_data"] or b"",
            self.validated_data["signature"],
            self.validated_data["entry_point"],
        )

        user_operation_hash = user_operation.calculate_user_operation_hash(
            self.validated_data["chain_id"]
        )

        user_operation_model, _ = UserOperationModel.objects.get_or_create(
            hash=user_operation_hash,
            defaults={
                "ethereum_tx": None,
                "sender": user_operation.sender,
                "nonce": user_operation.nonce,
                "init_code": user_operation.init_code,
                "call_data": user_operation.call_data,
                "call_gas_limit": user_operation.call_gas_limit,
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

        safe_operation_model, _ = SafeOperationModel.objects.get_or_create(
            hash=self.validated_data["safe_operation_hash"],
            defaults={
                "user_operation": user_operation_model,
                "valid_after": self.validated_data["valid_after"],
                "valid_until": self.validated_data["valid_until"],
                "module_address": self.validated_data["module_address"],
            },
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


class SafeOperationConfirmationSerializer(
    SafeOperationSignatureValidatorMixin, serializers.Serializer
):
    """
    Validate new confirmations for an existing `SafeOperation`
    """

    signature = eth_serializers.HexadecimalField(
        min_length=65, max_length=SIGNATURE_LENGTH
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        safe_operation_hash_hex = self.context["safe_operation_hash"]
        safe_operation_hash = HexBytes(safe_operation_hash_hex)

        try:
            user_operation_model: UserOperationModel = (
                UserOperationModel.objects.select_related("safe_operation").get(
                    safe_operation__hash=safe_operation_hash_hex
                )
            )
            safe_operation = user_operation_model.to_safe_operation()
        except UserOperationModel.DoesNotExist:
            raise ValidationError(
                f"SafeOperation with hash={safe_operation_hash_hex} does not exist"
            )

        # Parse valid owners from init code
        if user_operation_model.init_code:
            decoded_init_code = decode_init_code(
                bytes(user_operation_model.init_code), self.ethereum_client
            )
            self._deployment_owners = decoded_init_code.owners

        safe_signatures = self._validate_signature(
            safe_operation.safe,
            safe_operation_hash,
            safe_operation.safe_operation_hash_preimage,
            attrs["signature"],
        )
        if not safe_signatures:
            raise ValidationError("At least one signature must be provided")

        attrs["safe_operation_hash"] = safe_operation_hash_hex
        attrs["safe_signatures"] = safe_signatures
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        safe_signatures = self.validated_data["safe_signatures"]
        safe_operation_confirmations: List[SafeOperationConfirmation] = []
        for safe_signature in safe_signatures:
            safe_operation_confirmation, created = (
                SafeOperationConfirmation.objects.get_or_create(
                    safe_operation_id=self.context["safe_operation_hash"],
                    owner=safe_signature.owner,
                    defaults={
                        "signature": safe_signature.export_signature(),
                        "signature_type": safe_signature.signature_type.value,
                    },
                )
            )
            if created:
                safe_operation_confirmations.append(safe_operation_confirmation)

        return safe_operation_confirmations


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


class UserOperationResponseSerializer(serializers.Serializer):
    ethereum_tx_hash = eth_serializers.HexadecimalField(source="ethereum_tx_id")

    sender = eth_serializers.EthereumAddressField()
    user_operation_hash = eth_serializers.HexadecimalField(source="hash")
    nonce = serializers.IntegerField(min_value=0)
    init_code = eth_serializers.HexadecimalField(allow_null=True)
    call_data = eth_serializers.HexadecimalField(allow_null=True)
    call_gas_limit = serializers.IntegerField(min_value=0)
    verification_gas_limit = serializers.IntegerField(min_value=0)
    pre_verification_gas = serializers.IntegerField(min_value=0)
    max_fee_per_gas = serializers.IntegerField(min_value=0)
    max_priority_fee_per_gas = serializers.IntegerField(min_value=0)
    paymaster = eth_serializers.EthereumAddressField(allow_null=True)
    paymaster_data = eth_serializers.HexadecimalField(allow_null=True)
    signature = eth_serializers.HexadecimalField()
    entry_point = eth_serializers.EthereumAddressField()


class SafeOperationResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    modified = serializers.DateTimeField()
    safe_operation_hash = eth_serializers.HexadecimalField(source="hash")

    valid_after = serializers.DateTimeField()
    valid_until = serializers.DateTimeField()
    module_address = eth_serializers.EthereumAddressField()

    confirmations = serializers.SerializerMethodField()
    prepared_signature = serializers.SerializerMethodField()

    def get_confirmations(self, obj: SafeOperationModel) -> Dict[str, Any]:
        """
        Filters confirmations queryset

        :param obj: SafeOperation instance
        :return: Serialized queryset
        """
        return SafeOperationConfirmationResponseSerializer(
            obj.confirmations, many=True
        ).data

    def get_prepared_signature(self, obj: SafeOperationModel) -> HexStr:
        """
        Prepared signature sorted

        :param obj: SafeOperation instance
        :return: Serialized queryset
        """
        signature = obj.build_signature()
        return HexStr(HexBytes(signature).hex())


class SafeOperationWithUserOperationResponseSerializer(SafeOperationResponseSerializer):
    user_operation = UserOperationResponseSerializer(many=False, read_only=True)


class UserOperationWithSafeOperationResponseSerializer(UserOperationResponseSerializer):
    safe_operation = SafeOperationResponseSerializer(
        many=False, read_only=True, allow_null=True
    )
