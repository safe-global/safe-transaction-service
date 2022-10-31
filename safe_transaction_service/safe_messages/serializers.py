from rest_framework import serializers

import gnosis.eth.django.serializers as eth_serializers
from gnosis.safe.safe_signature import SafeSignatureType

from safe_transaction_service.safe_messages.models import SafeMessageConfirmation


class SafeMessageConfirmationSerializer(serializers.Serializer):
    owner = eth_serializers.EthereumAddressField()
    signature = eth_serializers.HexadecimalField()
    signature_type = serializers.SerializerMethodField()

    def get_signature_type(self, obj: SafeMessageConfirmation) -> str:
        return SafeSignatureType(obj.signature_type).name


class SafeMessageSerializer(serializers.Serializer):
    safe = eth_serializers.EthereumAddressField()
    message_hash = eth_serializers.Sha3HashField()
    message = serializers.JSONField()
    proposed_by = eth_serializers.EthereumAddressField()
    description = serializers.CharField()
    confirmations = serializers.ListField(child=SafeMessageConfirmationSerializer())
