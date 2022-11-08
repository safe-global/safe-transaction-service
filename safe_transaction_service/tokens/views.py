from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters.rest_framework
from rest_framework import response, status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import fast_is_checksum_address

from . import filters, serializers
from .clients import CannotGetPrice
from .models import Token
from .services import PriceServiceProvider


class TokenView(RetrieveAPIView):
    serializer_class = serializers.TokenInfoResponseSerializer
    lookup_field = "address"
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 60))  # Cache 1 hour, this does not change often
    def get(self, request, *args, **kwargs):
        address = self.kwargs["address"]
        if not fast_is_checksum_address(address):
            return response.Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Invalid ethereum address",
                    "arguments": [address],
                },
            )

        return super().get(request, *args, **kwargs)


class TokensView(ListAPIView):
    serializer_class = serializers.TokenInfoResponseSerializer
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    )
    filterset_class = filters.TokenFilter
    search_fields = ("name", "symbol")
    ordering_fields = "__all__"
    ordering = ("name",)
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 15))  # Cache 15 minutes
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TokenPriceView(RetrieveAPIView):
    serializer_class = serializers.TokenPriceResponseSerializer
    lookup_field = "address"
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 10))  # Cache 10 minutes
    def get(self, request, *args, **kwargs):
        address = self.kwargs["address"]
        if not fast_is_checksum_address(address):
            return response.Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Invalid ethereum address",
                    "arguments": [address],
                },
            )
        try:
            price_service = PriceServiceProvider()
            if address == NULL_ADDRESS:
                data = {
                    "fiat_code": "USD",
                    "fiat_price": str(price_service.get_native_coin_usd_price()),
                    "timestamp": timezone.now(),
                }
            else:
                token = self.get_object()  # Raises 404 if not found
                fiat_price_with_timestamp = next(
                    price_service.get_cached_usd_values([token.get_price_address()])
                )
                data = {
                    "fiat_code": fiat_price_with_timestamp.fiat_code.name,
                    "fiat_price": str(fiat_price_with_timestamp.fiat_price),
                    "timestamp": fiat_price_with_timestamp.timestamp,
                }
            serializer = self.get_serializer(data=data)
            assert serializer.is_valid()
            return Response(status=status.HTTP_200_OK, data=serializer.data)

        except CannotGetPrice:
            return Response(
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                data={
                    "code": 10,
                    "message": "Price retrieval failed",
                    "arguments": [address],
                },
            )
