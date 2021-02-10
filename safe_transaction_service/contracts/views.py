from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView

from . import pagination, serializers
from .models import Contract


class ContractView(RetrieveAPIView):
    lookup_field = 'address'
    queryset = Contract.objects.select_related('contract_abi')
    serializer_class = serializers.ContractSerializer

    @method_decorator(cache_page(60 * 60))  # Cache 1 hour
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ContractsView(ListAPIView):
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, OrderingFilter]
    ordering = ['address']
    ordering_fields = ['address', 'name']
    pagination_class = pagination.DefaultPagination
    queryset = Contract.objects.select_related('contract_abi')
    serializer_class = serializers.ContractSerializer
