import django_filters
from django_filters import rest_framework as filters

from gnosis.eth.django.filters import EthereumAddressFilter
from gnosis.eth.django.models import EthereumAddressField, Uint256Field

from .models import ModuleTransaction, MultisigTransaction


class TransferListFilter(filters.FilterSet):
    _from = django_filters.CharFilter()
    block_number = django_filters.NumberFilter(field_name='block_number')
    block_number__gt = django_filters.NumberFilter(field_name='block_number', lookup_expr='gt')
    block_number__lt = django_filters.NumberFilter(field_name='block_number', lookup_expr='lt')
    execution_date__gte = django_filters.IsoDateTimeFilter(field_name='execution_date', lookup_expr='gte')
    execution_date__lte = django_filters.IsoDateTimeFilter(field_name='execution_date', lookup_expr='lte')
    execution_date__gt = django_filters.IsoDateTimeFilter(field_name='execution_date', lookup_expr='gt')
    execution_date__lt = django_filters.IsoDateTimeFilter(field_name='execution_date', lookup_expr='lt')
    to = django_filters.CharFilter()
    token_address = django_filters.CharFilter()
    transaction_hash = django_filters.CharFilter(field_name='transaction_hash')
    value = django_filters.NumberFilter(field_name='value')
    value__gt = django_filters.NumberFilter(field_name='value', lookup_expr='gt')
    value__lt = django_filters.NumberFilter(field_name='value', lookup_expr='lt')


class MultisigTransactionFilter(filters.FilterSet):
    executed = django_filters.BooleanFilter(method='filter_executed')
    has_confirmations = django_filters.BooleanFilter(method='filter_confirmations')
    trusted = django_filters.BooleanFilter(method='filter_trusted')
    execution_date__gte = django_filters.IsoDateTimeFilter(field_name='ethereum_tx__block__timestamp',
                                                           lookup_expr='gte')
    execution_date__lte = django_filters.IsoDateTimeFilter(field_name='ethereum_tx__block__timestamp',
                                                           lookup_expr='lte')
    submission_date__gte = django_filters.IsoDateTimeFilter(field_name='created', lookup_expr='gte')
    submission_date__lte = django_filters.IsoDateTimeFilter(field_name='created', lookup_expr='lte')
    transaction_hash = django_filters.CharFilter(field_name='ethereum_tx_id')

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
            'failed': ['exact'],
            'modified': ['lt', 'gt', 'lte', 'gte'],
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


class ModuleTransactionFilter(filters.FilterSet):
    block_number = django_filters.NumberFilter(field_name='internal_tx__ethereum_tx__block_id')
    block_number__gt = django_filters.NumberFilter(field_name='internal_tx__ethereum_tx__block_id',
                                                   lookup_expr='gt')
    block_number__lt = django_filters.NumberFilter(field_name='internal_tx__ethereum_tx__block_id',
                                                   lookup_expr='lt')
    transaction_hash = django_filters.CharFilter(field_name='internal_tx__ethereum_tx_id')

    class Meta:
        model = ModuleTransaction
        fields = {
            'safe': ['exact'],
            'module': ['exact'],
            'to': ['exact'],
            'operation': ['exact'],
            'failed': ['exact'],
        }

        filter_overrides = {
            Uint256Field: {
                'filter_class': django_filters.NumberFilter
            },
            EthereumAddressField: {
                'filter_class': EthereumAddressFilter
            }
        }


class AnalyticsMultisigTxsByOriginFilter(filters.FilterSet):
    class Meta:
        model = MultisigTransaction
        fields = {
            'safe': ['exact'],
            'to': ['exact'],
            'value': ['lt', 'gt', 'lte', 'gte', 'exact'],
            'operation': ['exact'],
            'failed': ['exact'],
            'safe_tx_gas': ['lt', 'gt', 'lte', 'gte', 'exact'],
            'base_gas': ['lt', 'gt', 'lte', 'gte', 'exact'],
            'gas_price': ['lt', 'gt', 'lte', 'gte', 'exact'],
            'gas_token': ['exact'],
            'refund_receiver': ['exact'],
            'trusted': ['exact'],
        }

        filter_overrides = {
            Uint256Field: {
                'filter_class': django_filters.NumberFilter
            },
            EthereumAddressField: {
                'filter_class': EthereumAddressFilter
            }
        }


class AnalyticsMultisigTxsBySafeFilter(filters.FilterSet):
    master_copy = django_filters.CharFilter()
