from rest_framework import serializers

import gnosis.eth.django.serializers as eth_serializers


class SafeMessageConfirmationSerializer(serializers.Serializer):
    name = serializers.CharField()
    display_name = serializers.CharField()
    logo_uri = serializers.ImageField(source="logo")
    contract_abi = ContractAbiSerializer()
    trusted_for_delegate_call = serializers.BooleanField()


class SafeMessageSerializer(serializers.Serializer):
    safe = eth_serializers.EthereumAddressField()
    message_hash = eth_serializers.Sha3HashField()
    message = serializers.JSONField()
    proposed_by = eth_serializers.EthereumAddressField()
    description = serializers.CharField()
    confirmations = serializers.ListField(child=SafeMessageConfirmationSerializer())
