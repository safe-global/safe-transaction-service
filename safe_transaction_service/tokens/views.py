# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters.rest_framework
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import response, status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from safe_eth.eth.utils import fast_is_checksum_address

from ..history.serializers import CodeErrorResponse
from . import filters, serializers
from .models import Token, TokenList

logger = logging.getLogger(__name__)


@extend_schema(
    responses={
        200: OpenApiResponse(response=serializers.TokenInfoResponseSerializer),
        422: OpenApiResponse(
            response=CodeErrorResponse, description="Invalid ethereum address"
        ),
    }
)
class TokenView(RetrieveAPIView):
    serializer_class = serializers.TokenInfoResponseSerializer
    lookup_field = "address"
    queryset = Token.objects.all()

    def get_object(self) -> Token:
        try:
            return super().get_object()
        except Http404:
            # Tokens are catalogued lazily (balances/collectibles), so ones seen
            # only in transaction history are missing; fetch on demand.
            address = self.kwargs[self.lookup_field]
            try:
                token = Token.objects.create_from_blockchain(address)
            except Exception:
                # Don't let an RPC failure turn this into a 5xx storm; 404 instead.
                logger.warning(
                    "Could not fetch token=%s from blockchain", address, exc_info=True
                )
                token = None
            if token is None:
                raise
            return token

    @method_decorator(cache_page(60 * 60))  # Cache 1 hour, this does not change often
    def get(self, request, *args, **kwargs):
        """
        Returns detailed information on a given token supported in the Safe Transaction Service
        """
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
        """
        Returns the list of tokens supported in the Safe Transaction Service
        """
        return super().get(request, *args, **kwargs)


class TokenListsView(ListAPIView):
    serializer_class = serializers.TokenListSerializer
    ordering = ("pk",)
    queryset = TokenList.objects.all()

    @method_decorator(cache_page(60 * 15))  # Cache 15 minutes
    def get(self, request, *args, **kwargs):
        """
        Returns the list of tokens supported in the Safe Transaction Service
        """
        return super().get(request, *args, **kwargs)
