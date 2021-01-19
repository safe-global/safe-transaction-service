from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField

from safe_transaction_service.contracts.models import Contract


class ContractAbiSerializer(serializers.Serializer):
    abi = serializers.ListField(child=serializers.DictField())
    description = serializers.CharField()
    relevance = serializers.IntegerField()


class ContractSerializer(serializers.Serializer):
    address = EthereumAddressField()
    name = serializers.SerializerMethodField()
    logo_uri = serializers.ImageField(source='logo')
    contract_abi = ContractAbiSerializer()

    def get_name(self, obj: Contract):
        return obj.get_main_name()
