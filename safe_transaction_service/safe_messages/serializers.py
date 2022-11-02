from typing import Any, Dict

from rest_framework import serializers

import gnosis.eth.django.serializers as eth_serializers
from gnosis.safe.safe_signature import SafeSignatureType

from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)


# Request serializers
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
