from django_filters import rest_framework as filters
from safe_eth.eth.django.filters import EthereumAddressFilter
from safe_eth.eth.django.models import EthereumAddressBinaryField

from .models import Token


class TokenFilter(filters.FilterSet):
    class Meta:
        model = Token
        fields = {
            "name": ["exact"],
            "address": ["exact"],
            "symbol": ["exact"],
            "decimals": ["lt", "gt", "exact"],
        }
        filter_overrides = {
            EthereumAddressBinaryField: {"filter_class": EthereumAddressFilter},
        }
