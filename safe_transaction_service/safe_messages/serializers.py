from typing import Any, Dict, Union

from eth_account.messages import defunct_hash_message
from eth_typing import Hash32
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

import gnosis.eth.django.serializers as eth_serializers
from gnosis.eth import EthereumClientProvider
from gnosis.eth.eip712 import eip712_encode_hash
from gnosis.safe import Safe
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.utils.serializers import get_safe_owners


# Request serializers
class SafeMessageSerializer(serializers.Serializer):
    message = serializers.JSONField()
    description = serializers.CharField()
    signature = eth_serializers.HexadecimalField(max_length=65)

    def validate_message(self, value: Union[str, Dict[str, Any]]):
        if isinstance(value, str):
            return value

        if isinstance(value, dict):
            try:
                eip712_encode_hash(value)
                return value
            except ValueError:
                raise ValidationError(
                    f"Provided dictionary is not a valid EIP712 message {value}"
                )

        raise ValidationError(f"Provided value is not a valid message {value}")

    def validate(self, attrs):
        message = attrs["message"]
        safe_address = self.context["safe_address"]
        signature = attrs["signature"]
        attrs["safe"] = safe_address

        message_hash: Hash32 = (
            defunct_hash_message(text=message)
            if isinstance(message, str)
            else eip712_encode_hash(message)
        )
        ethereum_client = EthereumClientProvider()
        safe = Safe(safe_address, ethereum_client)
        safe_message_hash = safe.get_message_hash(message_hash)
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


# Reponse serializers
class SafeMessageConfirmationResponseSerializer(serializers.Serializer):
    owner = eth_serializers.EthereumAddressField()
    signature = eth_serializers.HexadecimalField()
    signature_type = serializers.SerializerMethodField()

    def get_signature_type(self, obj: SafeMessageConfirmation) -> str:
        return SafeSignatureType(obj.signature_type).name


class SafeMessageResponseSerializer(serializers.Serializer):
    safe = eth_serializers.EthereumAddressField()
    message_hash = eth_serializers.Sha3HashField()
    message = serializers.JSONField()
    proposed_by = eth_serializers.EthereumAddressField()
    description = serializers.CharField()
    confirmations = serializers.SerializerMethodField()

    def get_confirmations(self, obj: SafeMessage) -> Dict[str, Any]:
        """
        Filters confirmations queryset

        :param obj: SafeMessage instance
        :return: Serialized queryset
        """
        return SafeMessageConfirmationResponseSerializer(
            obj.confirmations, many=True
        ).data
