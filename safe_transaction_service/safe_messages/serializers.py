from typing import Any, Dict, Optional, Union

from eth_typing import HexStr
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

import gnosis.eth.django.serializers as eth_serializers
from gnosis.eth import EthereumClientProvider
from gnosis.eth.eip712 import eip712_encode_hash
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.utils.serializers import get_safe_owners

from .models import SafeMessage, SafeMessageConfirmation
from .utils import get_safe_message_hash_for_message


# Request serializers
class SafeMessageSerializer(serializers.Serializer):
    message = serializers.JSONField()
    safe_app_id = serializers.IntegerField(allow_null=True, default=None)
    signature = eth_serializers.HexadecimalField(max_length=65)

    def validate_message(self, value: Union[str, Dict[str, Any]]):
        if isinstance(value, str):
            return value

        if isinstance(value, dict):
            try:
                eip712_encode_hash(value)
                return value
            except ValueError as exc:
                raise ValidationError(
                    f"Provided dictionary is not a valid EIP712 message {value}"
                ) from exc

        raise ValidationError(f"Provided value is not a valid message {value}")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        message = attrs["message"]
        safe_address = self.context["safe_address"]
        signature = attrs["signature"]
        attrs["safe"] = safe_address
        safe_message_hash = get_safe_message_hash_for_message(safe_address, message)
        attrs["message_hash"] = safe_message_hash

        if SafeMessage.objects.filter(message_hash=safe_message_hash).exists():
            raise ValidationError(
                f"Message with hash {safe_message_hash.hex()} for safe {safe_address} already exists in DB"
            )

        safe_signatures = SafeSignature.parse_signature(signature, safe_message_hash)
        if len(safe_signatures) != 1:
            raise ValidationError(
                f"1 owner signature was expected, {len(safe_signatures)} received"
            )

        ethereum_client = EthereumClientProvider()
        for safe_signature in safe_signatures:
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={safe_signature.signature.hex()} for owner={safe_signature.owner} is not valid"
                )

        owners = get_safe_owners(safe_address)
        proposed_by = safe_signatures[0].owner
        if proposed_by not in owners:
            raise ValidationError(f"{proposed_by} is not an owner of the Safe")

        attrs["proposed_by"] = proposed_by
        attrs["signature_type"] = safe_signatures[0].signature_type.value
        return attrs

    def create(self, validated_data):
        signature = validated_data.pop("signature")
        signature_type = validated_data.pop("signature_type")

        safe_message = SafeMessage.objects.create(**validated_data)
        SafeMessageConfirmation.objects.create(
            safe_message=safe_message,
            owner=validated_data["proposed_by"],
            signature=signature,
            signature_type=signature_type,
        )
        return safe_message


class SafeMessageSignatureSerializer(serializers.Serializer):
    signature = eth_serializers.HexadecimalField(max_length=65)

    def validate(self, attrs):
        attrs = super().validate(attrs)

        safe_message: SafeMessage = self.context["safe_message"]
        attrs["safe_message"] = safe_message
        signature: HexStr = attrs["signature"]
        safe_address = safe_message.safe
        safe_message_hash = safe_message.message_hash

        safe_signatures = SafeSignature.parse_signature(signature, safe_message_hash)
        if len(safe_signatures) != 1:
            raise ValidationError(
                f"1 owner signature was expected, {len(safe_signatures)} received"
            )

        ethereum_client = EthereumClientProvider()
        for safe_signature in safe_signatures:
            if not safe_signature.is_valid(ethereum_client, safe_address):
                raise ValidationError(
                    f"Signature={safe_signature.signature.hex()} for owner={safe_signature.owner} is not valid"
                )

        owner = safe_signatures[0].owner
        if SafeMessageConfirmation.objects.filter(
            safe_message=safe_message, owner=owner
        ).exists():
            raise ValidationError(f"Signature for owner {owner} already exists")

        owners = get_safe_owners(safe_address)
        if owner not in owners:
            raise ValidationError(f"{owner} is not an owner of the Safe")

        attrs["owner"] = owner
        attrs["signature_type"] = safe_signatures[0].signature_type.value
        return attrs

    def create(self, validated_data):
        safe_message_confirmation = SafeMessageConfirmation.objects.create(
            **validated_data
        )
        safe_message = validated_data["safe_message"]
        SafeMessage.objects.filter(pk=safe_message.pk).update(
            modified=safe_message_confirmation.modified
        )
        return safe_message_confirmation


# Reponse serializers
class SafeMessageConfirmationResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    modified = serializers.DateTimeField()
    owner = eth_serializers.EthereumAddressField()
    signature = eth_serializers.HexadecimalField()
    signature_type = serializers.SerializerMethodField()

    def get_signature_type(self, obj: SafeMessageConfirmation) -> str:
        return SafeSignatureType(obj.signature_type).name


class SafeMessageResponseSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    modified = serializers.DateTimeField()
    safe = eth_serializers.EthereumAddressField()
    message_hash = eth_serializers.Sha3HashField()
    message = serializers.JSONField()
    proposed_by = eth_serializers.EthereumAddressField()
    safe_app_id = serializers.IntegerField()
    confirmations = serializers.SerializerMethodField()
    prepared_signature = serializers.SerializerMethodField()

    def get_confirmations(self, obj: SafeMessage) -> Dict[str, Any]:
        """
        Filters confirmations queryset

        :param obj: SafeMessage instance
        :return: Serialized queryset
        """
        return SafeMessageConfirmationResponseSerializer(
            obj.confirmations, many=True
        ).data

    def get_prepared_signature(self, obj: SafeMessage) -> Optional[str]:
        """
        Prepared signature sorted

        :param obj: SafeMessage instance
        :return: Serialized queryset
        """
        signature = HexBytes(obj.build_signature())
        return HexBytes(signature).hex() if signature else None
