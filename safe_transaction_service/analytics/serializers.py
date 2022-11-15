from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField


class AnalyticsMultisigTxsByOriginResponseSerializer(serializers.Serializer):
    origin = serializers.CharField()
    transactions = serializers.IntegerField()


class AnalyticsMultisigTxsBySafeResponseSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    master_copy = EthereumAddressField()
    transactions = serializers.IntegerField()
