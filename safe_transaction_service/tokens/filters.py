from django_filters import rest_framework as filters

from gnosis.eth.django.filters import EthereumAddressFilter
from gnosis.eth.django.models import EthereumAddressV2Field

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
            EthereumAddressV2Field: {"filter_class": EthereumAddressFilter},
        }
