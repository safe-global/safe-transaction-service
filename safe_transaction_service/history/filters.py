from django.db.models import Q

import django_filters
from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from gnosis.eth.django.filters import EthereumAddressFilter, Keccak256Filter
from gnosis.eth.django.models import (
    EthereumAddressField,
    EthereumAddressV2Field,
    Keccak256Field,
    Uint256Field,
)

from .models import ModuleTransaction, MultisigTransaction

filter_overrides = {
    Uint256Field: {"filter_class": django_filters.NumberFilter},
    Keccak256Field: {"filter_class": Keccak256Filter},
    EthereumAddressField: {"filter_class": EthereumAddressFilter},
    EthereumAddressV2Field: {"filter_class": EthereumAddressFilter},
}


class DelegateListFilter(filters.FilterSet):
    safe = EthereumAddressFilter(field_name="safe_contract_id")
    delegate = EthereumAddressFilter()
    delegator = EthereumAddressFilter()
    label = django_filters.CharFilter()

    def filter_queryset(self, queryset):
        # Check at least one value is present
        for name, value in self.form.cleaned_data.items():
            if value:
                return super().filter_queryset(queryset)
        raise ValidationError("At least one query param must be provided")


class TransferListFilter(filters.FilterSet):
    _from = EthereumAddressFilter()
    block_number = django_filters.NumberFilter(field_name="block")
    block_number__gt = django_filters.NumberFilter(field_name="block", lookup_expr="gt")
    block_number__lt = django_filters.NumberFilter(field_name="block", lookup_expr="lt")
    execution_date__gte = django_filters.IsoDateTimeFilter(
        field_name="execution_date", lookup_expr="gte"
    )
    execution_date__lte = django_filters.IsoDateTimeFilter(
        field_name="execution_date", lookup_expr="lte"
    )
    execution_date__gt = django_filters.IsoDateTimeFilter(
        field_name="execution_date", lookup_expr="gt"
    )
    execution_date__lt = django_filters.IsoDateTimeFilter(
        field_name="execution_date", lookup_expr="lt"
    )
    to = EthereumAddressFilter()
    token_address = EthereumAddressFilter()
    transaction_hash = Keccak256Filter(field_name="transaction_hash")
    value = django_filters.NumberFilter(field_name="_value")
    value__gt = django_filters.NumberFilter(field_name="_value", lookup_expr="gt")
    value__lt = django_filters.NumberFilter(field_name="_value", lookup_expr="lt")
    erc20 = django_filters.BooleanFilter(method="filter_erc20")
    erc721 = django_filters.BooleanFilter(method="filter_erc721")
    ether = django_filters.BooleanFilter(method="filter_ether")

    def filter_erc20(self, queryset, name: str, value: bool):
        query = ~Q(_value=None) & ~Q(token_address=None)
        if value:
            return queryset.filter(query)
        else:
            return queryset.exclude(query)

    def filter_erc721(self, queryset, name: str, value: bool):
        query = ~Q(_token_id=None)
        if value:
            return queryset.filter(query)
        else:
            return queryset.exclude(query)

    def filter_ether(self, queryset, name: str, value: bool):
        query = ~Q(_value=None) & Q(token_address=None)
        if value:
            return queryset.filter(query)
        else:
            return queryset.exclude(query)


class MultisigTransactionFilter(filters.FilterSet):
    executed = django_filters.BooleanFilter(method="filter_executed")
    has_confirmations = django_filters.BooleanFilter(method="filter_confirmations")
    trusted = django_filters.BooleanFilter(method="filter_trusted")
    execution_date__gte = django_filters.IsoDateTimeFilter(
        field_name="ethereum_tx__block__timestamp", lookup_expr="gte"
    )
    execution_date__lte = django_filters.IsoDateTimeFilter(
        field_name="ethereum_tx__block__timestamp", lookup_expr="lte"
    )
    submission_date__gte = django_filters.IsoDateTimeFilter(
        field_name="created", lookup_expr="gte"
    )
    submission_date__lte = django_filters.IsoDateTimeFilter(
        field_name="created", lookup_expr="lte"
    )
    transaction_hash = Keccak256Filter(field_name="ethereum_tx_id")

    def filter_confirmations(self, queryset, name: str, value: bool):
        if value:
            return queryset.with_confirmations()
        else:
            return queryset.without_confirmations()

    def filter_executed(self, queryset, name: str, value: bool):
        if value:
            return queryset.executed()
        else:
            return queryset.not_executed()

    def filter_trusted(self, queryset, name: str, value: bool):
        return queryset.filter(trusted=value)

    class Meta:
        model = MultisigTransaction
        fields = {
            "failed": ["exact"],
            "modified": ["lt", "gt", "lte", "gte"],
            "nonce": ["lt", "gt", "lte", "gte", "exact"],
            "safe_tx_hash": ["exact"],
            "to": ["exact"],
            "value": ["lt", "gt", "exact"],
        }
        filter_overrides = filter_overrides


class ModuleTransactionFilter(filters.FilterSet):
    block_number = django_filters.NumberFilter(
        field_name="internal_tx__ethereum_tx__block_id"
    )
    block_number__gt = django_filters.NumberFilter(
        field_name="internal_tx__ethereum_tx__block_id", lookup_expr="gt"
    )
    block_number__lt = django_filters.NumberFilter(
        field_name="internal_tx__ethereum_tx__block_id", lookup_expr="lt"
    )
    transaction_hash = Keccak256Filter(field_name="internal_tx__ethereum_tx_id")

    class Meta:
        model = ModuleTransaction
        fields = {
            "safe": ["exact"],
            "module": ["exact"],
            "to": ["exact"],
            "operation": ["exact"],
            "failed": ["exact"],
        }

        filter_overrides = filter_overrides
