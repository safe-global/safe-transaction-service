from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField


class ContractAbiSerializer(serializers.Serializer):
    abi = serializers.ListField(child=serializers.DictField())
    description = serializers.CharField()
    relevance = serializers.IntegerField()


class ContractSerializer(serializers.Serializer):
    address = EthereumAddressField()
    name = serializers.CharField()
    display_name = serializers.CharField()
    logo_uri = serializers.ImageField(source='logo')
    contract_abi = ContractAbiSerializer()
