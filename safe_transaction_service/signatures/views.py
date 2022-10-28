from django.core.cache import cache as django_cache

import django_filters
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView

from . import pagination, serializers
from .models import Contract


class ContractView(RetrieveAPIView):
    lookup_field = "address"
    queryset = Contract.objects.select_related("contract_abi")
    serializer_class = serializers.ContractSerializer

    def get(self, request, address, *args, **kwargs):
        cache_key = get_contract_cache_key(address)
        if not (response := django_cache.get(cache_key)):
            response = super().get(request, address, *args, **kwargs)
            response.add_post_render_callback(
                lambda r: (
                    django_cache.set(
                        cache_key, response, timeout=60 * 60
                    ),  # Cache 1 hour:
                    r,
                )[
                    1
                ]  # Return r, if not redis has issues
            )
        return response


class ContractsView(ListAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["address"]
    ordering_fields = ["address", "name"]
    pagination_class = pagination.DefaultPagination
    queryset = Contract.objects.select_related("contract_abi")
    serializer_class = serializers.ContractSerializer
