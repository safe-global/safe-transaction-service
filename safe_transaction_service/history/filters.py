import django_filters
from django_filters import BooleanFilter
from django_filters import rest_framework as filters
from rest_framework.pagination import LimitOffsetPagination

from gnosis.eth.django.models import Uint256Field

from .models import MultisigTransaction


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100


class MultisigTransactionFilter(filters.FilterSet):
    executed = BooleanFilter(method='filter_executed')

    def filter_executed(self, queryset, name: str, value: bool):
        if value:
            return queryset.executed()
        else:
            return queryset.not_executed()

    class Meta:
        model = MultisigTransaction
        fields = {
            'value': ['lt', 'gt', 'exact'],
            'nonce': ['lt', 'gt', 'exact'],
            'executed': ['exact'],
        }
        filter_overrides = {
            Uint256Field: {
                'filter_class': django_filters.NumberFilter
            }
        }
