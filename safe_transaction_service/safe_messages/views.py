import django_filters
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from gnosis.eth.utils import fast_is_checksum_address

from . import pagination, serializers
from .models import SafeMessage


class SafeMessageView(RetrieveAPIView):
    lookup_field = "id"
    queryset = SafeMessage.objects.prefetch_related("confirmations")
    serializer_class = serializers.SafeMessageResponseSerializer


class SafeMessagesView(ListAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-created"]
    ordering_fields = ["created", "modified"]
    pagination_class = pagination.DefaultPagination
    serializer_class = serializers.SafeMessageResponseSerializer

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

    def get_queryset(self):
        safe = self.kwargs["address"]
        return SafeMessage.objects.filter(safe=safe).prefetch_related("confirmations")
