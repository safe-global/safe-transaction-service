# SPDX-License-Identifier: FSL-1.1-MIT
import logging

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from safe_eth.eth.utils import fast_is_checksum_address

from safe_transaction_service.history.pagination import DefaultPagination

from . import filters, serializers
from .models import PolicyConfirmation, PolicyEngineEvent, PolicyRootRequest

logger = logging.getLogger(__name__)


class SafePolicyEventListView(ListAPIView):
    """
    Base view for the policy guard events of a single Safe. Not routed, subclasses set
    `model`, `filterset_class` and `serializer_class`.
    """

    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-timestamp", "-log_index"]
    ordering_fields = ["timestamp", "block_number"]
    pagination_class = DefaultPagination
    model: type[PolicyEngineEvent]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.model.objects.none()

        return self.model.objects.filter(safe=self.kwargs["address"]).select_related(
            "ethereum_tx"
        )

    def get(self, request, address, *args, **kwargs):
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )
        return super().get(request, address, *args, **kwargs)


class SafePolicyConfirmationsView(SafePolicyEventListView):
    filterset_class = filters.PolicyConfirmationFilter
    model = PolicyConfirmation
    serializer_class = serializers.PolicyConfirmationResponseSerializer

    @extend_schema(tags=["policies"])
    def get(self, request, address, *args, **kwargs):
        """
        Returns the policies confirmed for a given Safe account, newest first.

        One entry per `PolicyConfirmed` event, so the history of a target, selector and
        operation is kept. An entry with an empty `policy` removed the policy.
        """
        return super().get(request, address, *args, **kwargs)


class SafePolicyRootRequestsView(SafePolicyEventListView):
    filterset_class = filters.PolicyRootRequestFilter
    model = PolicyRootRequest
    serializer_class = serializers.PolicyRootRequestResponseSerializer

    def get_queryset(self):
        return super().get_queryset().with_status()

    @extend_schema(tags=["policies"])
    def get(self, request, address, *args, **kwargs):
        """
        Returns the delayed policy configurations requested for a given Safe account,
        newest first.

        One entry per `RootConfigured` event. `status` is `pending` until `valid_from`,
        then `ready`, or `invalidated` if it was cancelled through `invalidateRoot`.
        """
        return super().get(request, address, *args, **kwargs)
