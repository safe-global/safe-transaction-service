from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters.rest_framework
from rest_framework import filters
from rest_framework.generics import ListAPIView, RetrieveAPIView

from safe_transaction_service.history.services import (
    BalanceServiceProvider, CollectiblesServiceProvider)

from .filters import TokenFilter
from .models import Token
from .serializers import TokenInfoResponseSerializer


class TokenView(RetrieveAPIView):
    serializer_class = TokenInfoResponseSerializer
    lookup_field = 'address'
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 60 * 6))  # Cache 6 hours, this should never change
    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except Http404 as exc:  # Try to get info about the token
            address = self.kwargs['address']
            token_info = (BalanceServiceProvider().get_token_info(address)
                          or CollectiblesServiceProvider().get_token_info(address))  # TODO Refactor
            if not token_info:
                raise exc

            # If token was found it will be added to database, so we try again
            return super().get(request, *args, **kwargs)


class TokensView(ListAPIView):
    serializer_class = TokenInfoResponseSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    filterset_class = TokenFilter
    search_fields = ('name', 'symbol')
    ordering_fields = '__all__'
    ordering = ('name',)
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 15))  # Cache 15 minutes
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
