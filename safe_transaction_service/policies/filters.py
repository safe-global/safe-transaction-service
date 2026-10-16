# SPDX-License-Identifier: FSL-1.1-MIT
import django_filters
from django_filters import rest_framework as filters
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.django.filters import EthereumAddressFilter, Keccak256Filter

from safe_transaction_service.utils.filters import HexFilter, filter_overrides

from .models import (
    FALLBACK_SELECTOR,
    PolicyConfirmation,
    PolicyRootRequest,
    PolicyRootStatus,
)


class PolicyConfirmationFilter(filters.FilterSet):
    target = EthereumAddressFilter()
    selector = HexFilter()
    policy = EthereumAddressFilter()
    removed = django_filters.BooleanFilter(method="filter_removed")
    fallback = django_filters.BooleanFilter(method="filter_fallback")
    transaction_hash = Keccak256Filter(field_name="ethereum_tx_id")
    timestamp__gte = django_filters.IsoDateTimeFilter(
        field_name="timestamp", lookup_expr="gte"
    )
    timestamp__lte = django_filters.IsoDateTimeFilter(
        field_name="timestamp", lookup_expr="lte"
    )

    def filter_removed(self, queryset, _name: str, value: bool):
        return (
            queryset.filter(policy=NULL_ADDRESS)
            if value
            else queryset.exclude(policy=NULL_ADDRESS)
        )

    def filter_fallback(self, queryset, _name: str, value: bool):
        fallback = {"target": NULL_ADDRESS, "selector": FALLBACK_SELECTOR}
        return queryset.filter(**fallback) if value else queryset.exclude(**fallback)

    class Meta:
        model = PolicyConfirmation
        fields = {
            "operation": ["exact"],
            "block_number": ["exact", "gte", "lte"],
        }
        filter_overrides = filter_overrides


class PolicyRootRequestFilter(filters.FilterSet):
    root = Keccak256Filter()
    # Annotated by `PolicyRootRequestQuerySet.with_status`
    status = django_filters.ChoiceFilter(choices=PolicyRootStatus.choices)
    transaction_hash = Keccak256Filter(field_name="ethereum_tx_id")
    timestamp__gte = django_filters.IsoDateTimeFilter(
        field_name="timestamp", lookup_expr="gte"
    )
    timestamp__lte = django_filters.IsoDateTimeFilter(
        field_name="timestamp", lookup_expr="lte"
    )
    valid_from__gte = django_filters.IsoDateTimeFilter(
        field_name="valid_from", lookup_expr="gte"
    )
    valid_from__lte = django_filters.IsoDateTimeFilter(
        field_name="valid_from", lookup_expr="lte"
    )

    class Meta:
        model = PolicyRootRequest
        fields = {"block_number": ["exact", "gte", "lte"]}
        filter_overrides = filter_overrides
