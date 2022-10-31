import django_filters
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView

from . import pagination, serializers
from .models import SafeMessage


class SafeMessageView(RetrieveAPIView):
    lookup_field = "id"
    queryset = SafeMessage.objects.prefetch_related("confirmations")
    serializer_class = serializers.SafeMessageSerializer


class SafeMessagesView(ListAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-created"]
    ordering_fields = ["created", "modified"]
    pagination_class = pagination.DefaultPagination
    queryset = SafeMessage.objects.prefetch_related("confirmations")
    serializer_class = serializers.SafeMessageSerializer
