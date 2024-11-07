import django_filters
from safe_eth.eth.django.filters import EthereumAddressFilter, Keccak256Filter
from safe_eth.eth.django.models import (
    EthereumAddressBinaryField,
    Keccak256Field,
    Uint256Field,
)

filter_overrides = {
    Uint256Field: {"filter_class": django_filters.NumberFilter},
    Keccak256Field: {"filter_class": Keccak256Filter},
    EthereumAddressBinaryField: {"filter_class": EthereumAddressFilter},
}
