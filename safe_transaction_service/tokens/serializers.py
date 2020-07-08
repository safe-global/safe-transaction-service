from enum import Enum

from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField

from .models import Token


class TokenTransferInfoType(Enum):
    ERC20 = 0
    ERC721 = 1


class TokenInfoResponseSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField()
    address = EthereumAddressField()
    name = serializers.CharField()
    symbol = serializers.CharField()
    decimals = serializers.IntegerField()
    logo_uri = serializers.SerializerMethodField()

    def get_type(self, obj: Token) -> str:
        if obj.decimals:
            return TokenTransferInfoType.ERC20.name
        else:
            return TokenTransferInfoType.ERC721.name

    def get_logo_uri(self, obj: Token) -> str:
        return obj.get_full_logo_uri()
