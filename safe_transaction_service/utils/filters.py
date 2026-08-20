# SPDX-License-Identifier: FSL-1.1-MIT
import django_filters
from safe_eth.eth.django.filters import EthereumAddressFilter, Keccak256Filter
from safe_eth.eth.django.forms import HexFieldForm
from safe_eth.eth.django.models import (
    EthereumAddressBinaryField,
    HexV2Field,
    Keccak256Field,
    Uint256Field,
)


class HexFilter(django_filters.Filter):
    """Filters a binary field by its hexadecimal representation, e.g. `0xa9059cbb`."""

    field_class = HexFieldForm


filter_overrides = {
    Uint256Field: {"filter_class": django_filters.NumberFilter},
    Keccak256Field: {"filter_class": Keccak256Filter},
    EthereumAddressBinaryField: {"filter_class": EthereumAddressFilter},
    HexV2Field: {"filter_class": HexFilter},
}
