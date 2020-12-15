from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField


class ContractAbiSerializer(serializers.Serializer):
    abi = serializers.ListField(child=serializers.DictField())
    description = serializers.CharField()
    relevance = serializers.IntegerField()


class ContractSerializer(serializers.Serializer):
    address = EthereumAddressField()
    name = serializers.CharField()
    contract_abi = ContractAbiSerializer()
