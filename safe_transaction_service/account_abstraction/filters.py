import django_filters
from django_filters import rest_framework as filters
from safe_eth.eth.django.filters import Keccak256Filter

from safe_transaction_service.utils.filters import filter_overrides

from .models import SafeOperation


class SafeOperationFilter(filters.FilterSet):
    executed = django_filters.BooleanFilter(method="filter_executed")
    has_confirmations = django_filters.BooleanFilter(method="filter_confirmations")
    execution_date__gte = django_filters.IsoDateTimeFilter(
        field_name="user_operation__ethereum_tx__block__timestamp", lookup_expr="gte"
    )
    execution_date__lte = django_filters.IsoDateTimeFilter(
        field_name="user_operation__ethereum_tx__block__timestamp", lookup_expr="lte"
    )
    submission_date__gte = django_filters.IsoDateTimeFilter(
        field_name="created", lookup_expr="gte"
    )
    submission_date__lte = django_filters.IsoDateTimeFilter(
        field_name="created", lookup_expr="lte"
    )
    transaction_hash = Keccak256Filter(field_name="user_operation__ethereum_tx_id")

    def filter_confirmations(self, queryset, _name: str, value: bool):
        if value:
            return queryset.with_confirmations()
        else:
            return queryset.without_confirmations()

    def filter_executed(self, queryset, _name: str, value: bool):
        if value:
            return queryset.executed()
        else:
            return queryset.not_executed()

    class Meta:
        model = SafeOperation
        fields = {
            "modified": ["lt", "gt", "lte", "gte"],
            "valid_after": ["lt", "gt", "lte", "gte"],
            "valid_until": ["lt", "gt", "lte", "gte"],
            "module_address": ["exact"],
        }
        filter_overrides = filter_overrides
