from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters.rest_framework
from rest_framework import response, status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from web3 import Web3

from . import filters, serializers
from .models import Token
from .services import PriceServiceProvider
from .services.price_service import FiatCode
from .tasks import get_token_info_from_blockchain


class TokenView(RetrieveAPIView):
    serializer_class = serializers.TokenInfoResponseSerializer
    lookup_field = 'address'
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 60))  # Cache 1 hour, this should never change
    def get(self, request, *args, **kwargs):
        address = self.kwargs['address']
        if not Web3.isChecksumAddress(address):
            return response.Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                     data={'code': 1,
                                           'message': 'Invalid ethereum address',
                                           'arguments': [address]})

        try:
            return super().get(request, *args, **kwargs)
        except Http404 as exc:  # Try to get info about the token
            get_token_info_from_blockchain.delay(address)
            raise exc


class TokensView(ListAPIView):
    serializer_class = serializers.TokenInfoResponseSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_class = filters.TokenFilter
    search_fields = ('name', 'symbol')
    ordering_fields = '__all__'
    ordering = ('name',)
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 15))  # Cache 15 minutes
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TokenPriceView(APIView):
    serializer_class = serializers.TokenPriceResponseSerializer
    lookup_field = 'address'
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 10))  # Cache 10 minutes
    def get(self, request, *args, **kwargs):
        address = self.kwargs['address']
        if not Web3.isChecksumAddress(address):
            return response.Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                     data={'code': 1,
                                           'message': 'Invalid ethereum address',
                                           'arguments': [address]})

        if not Token.objects.filter(address=address).exists():
            raise Http404
        usd_price = PriceServiceProvider().get_token_usd_price(address)
        serializer = self.serializer_class(data={'fiat_code': FiatCode.USD.name,
                                                 'fiat_price': str(usd_price)})
        assert serializer.is_valid()
        return Response(status=status.HTTP_200_OK, data=serializer.data)
