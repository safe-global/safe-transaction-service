import django_filters
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.response import Response

from gnosis.eth.utils import fast_is_checksum_address

from . import pagination, serializers
from .models import UserOperation


class SafeOperationView(RetrieveAPIView):
    lookup_field = "safe_operation__hash"
    lookup_url_kwarg = "safe_operation_hash"
    queryset = UserOperation.objects.prefetch_related("safe_operation__confirmations")
    serializer_class = serializers.SafeOperationResponseSerializer


class SafeOperationsView(ListCreateAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-created"]
    ordering_fields = ["created", "modified"]
    pagination_class = pagination.DefaultPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context

        context["safe_address"] = self.kwargs["address"]
        return context

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeOperationResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeOperationSerializer

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

    @swagger_auto_schema(
        request_body=serializers.SafeOperationSerializer,
        responses={201: "Created"},
    )
    def post(self, request, address, *args, **kwargs):
        """
        Create a new signed message for a Safe. Message can be:
        - A ``string``, so ``EIP191`` will be used to get the hash.
        - An ``EIP712`` ``object``.

        Hash will be calculated from the provided ``message``. Sending a raw ``hash`` will not be accepted,
        service needs to derive it itself.
        """
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(status=status.HTTP_201_CREATED)

    def get_queryset(self):
        safe = self.kwargs["address"]
        return UserOperation.objects.filter(sender=safe).prefetch_related(
            "safe_operation__confirmations"
        )
