import django_filters
from django_filters import rest_framework as filters
from rest_framework.pagination import LimitOffsetPagination

from gnosis.eth.django.models import Uint256Field

from .models import InternalTx, MultisigTransaction


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100


class IncomingTransactionFilter(filters.FilterSet):
    block_number__gt = django_filters.NumberFilter(lookup_expr='gt')
    block_number__lt = django_filters.NumberFilter(lookup_expr='gt')
    nonce__gt = django_filters.NumberFilter(lookup_expr='gt')
    nonce__lt = django_filters.NumberFilter(lookup_expr='lt')
    execution_date__gte = django_filters.DateTimeFilter(lookup_expr='gte')
    execution_date__lte = django_filters.DateTimeFilter(lookup_expr='lte')
    token_address = django_filters.CharFilter()

    class Meta:
        model = InternalTx
        fields = {
            '_from': ['exact'],
            'to': ['exact'],
            'value': ['lt', 'gt', 'exact'],
        }
        filter_overrides = {
            Uint256Field: {
                'filter_class': django_filters.NumberFilter
            }
        }


class MultisigTransactionFilter(filters.FilterSet):
    executed = django_filters.BooleanFilter(method='filter_executed')
    execution_date__gte = django_filters.DateTimeFilter(field_name='ethereum_tx__block__timestamp', lookup_expr='gte')
    execution_date__lte = django_filters.DateTimeFilter(field_name='ethereum_tx__block__timestamp', lookup_expr='lte')
    submission_date__gte = django_filters.DateTimeFilter(field_name='created', lookup_expr='gte')
    submission_date__lte = django_filters.DateTimeFilter(field_name='created', lookup_expr='lte')
    transaction_hash = django_filters.CharFilter(field_name='ethereum_tx_id')

    def filter_executed(self, queryset, name: str, value: bool):
        if value:
            return queryset.executed()
        else:
            return queryset.not_executed()

    class Meta:
        model = MultisigTransaction
        fields = {
            'executed': ['exact'],
            'nonce': ['lt', 'gt', 'exact'],
            'safe_tx_hash': ['exact'],
            'value': ['lt', 'gt', 'exact'],
        }
        filter_overrides = {
            Uint256Field: {
                'filter_class': django_filters.NumberFilter
            }
        }
