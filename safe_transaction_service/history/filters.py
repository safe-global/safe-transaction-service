import django_filters
from django_filters import rest_framework as filters
from rest_framework.pagination import LimitOffsetPagination

from gnosis.eth.django.filters import EthereumAddressFilter
from gnosis.eth.django.models import EthereumAddressField, Uint256Field

from .models import MultisigTransaction


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100


class IncomingTransactionFilter(filters.FilterSet):
    _from = django_filters.CharFilter()
    block_number = django_filters.NumberFilter(field_name='block_number')
    block_number__gt = django_filters.NumberFilter(field_name='block_number', lookup_expr='gt')
    block_number__lt = django_filters.NumberFilter(field_name='block_number', lookup_expr='lt')
    execution_date__gte = django_filters.IsoDateTimeFilter(field_name='execution_date', lookup_expr='gte')
    execution_date__lte = django_filters.IsoDateTimeFilter(field_name='execution_date', lookup_expr='lte')
    nonce__gt = django_filters.NumberFilter(lookup_expr='gt')
    nonce__lt = django_filters.NumberFilter(lookup_expr='lt')
    to = django_filters.CharFilter()
    token_address = django_filters.CharFilter()
    value = django_filters.NumberFilter(field_name='value')
    value__gt = django_filters.NumberFilter(field_name='value', lookup_expr='gt')
    value__lt = django_filters.NumberFilter(field_name='value', lookup_expr='lt')


class MultisigTransactionFilter(filters.FilterSet):
    executed = django_filters.BooleanFilter(method='filter_executed')
    execution_date__gte = django_filters.IsoDateTimeFilter(field_name='ethereum_tx__block__timestamp',
                                                           lookup_expr='gte')
    execution_date__lte = django_filters.IsoDateTimeFilter(field_name='ethereum_tx__block__timestamp',
                                                           lookup_expr='lte')
    submission_date__gte = django_filters.IsoDateTimeFilter(field_name='created', lookup_expr='gte')
    submission_date__lte = django_filters.IsoDateTimeFilter(field_name='created', lookup_expr='lte')
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
            'failed': ['exact'],
            'nonce': ['lt', 'gt', 'lte', 'gte', 'exact'],
            'safe_tx_hash': ['exact'],
            'to': ['exact'],
            'value': ['lt', 'gt', 'exact'],
        }
        filter_overrides = {
            Uint256Field: {
                'filter_class': django_filters.NumberFilter
            },
            EthereumAddressField: {
                'filter_class': EthereumAddressFilter
            }
        }
