from enum import Enum

from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField

from .models import Token


class TokenTransferInfoType(Enum):
    UNKNOWN = -1
    ERC20 = 0
    ERC721 = 1


class TokenInfoResponseSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField()
    address = EthereumAddressField()
    name = serializers.CharField()
    symbol = serializers.CharField()
    decimals = serializers.IntegerField()
    logo_uri = serializers.SerializerMethodField()
    trusted = serializers.BooleanField()

    def get_type(self, obj: Token) -> str:
        if obj.is_erc20():
            return TokenTransferInfoType.ERC20.name
        elif obj.is_erc721():
            return TokenTransferInfoType.ERC721.name
        else:
            return TokenTransferInfoType.UNKNOWN.name

    def get_logo_uri(self, obj: Token) -> str:
        return obj.get_full_logo_uri()


class TokenPriceResponseSerializer(serializers.Serializer):
    fiat_code = serializers.CharField()
    fiat_price = serializers.CharField()
    timestamp = serializers.DateTimeField()
