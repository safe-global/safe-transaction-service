import django_filters
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.response import Response
from safe_eth.eth.utils import fast_is_checksum_address

from . import filters, pagination, serializers
from .models import SafeOperation, SafeOperationConfirmation, UserOperation


@extend_schema(tags=["4337"])
class SafeOperationView(RetrieveAPIView):
    """
    Returns a SafeOperation given its Safe operation hash
    """

    lookup_field = "hash"
    lookup_url_kwarg = "safe_operation_hash"
    queryset = SafeOperation.objects.prefetch_related("confirmations").select_related(
        "user_operation"
    )
    serializer_class = serializers.SafeOperationWithUserOperationResponseSerializer


class SafeOperationsView(ListCreateAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    filterset_class = filters.SafeOperationFilter
    ordering = ["-user_operation__nonce", "-created"]
    ordering_fields = ["user_operation__nonce", "created"]
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SafeOperation.objects.none()

        safe = self.kwargs["address"]
        return (
            SafeOperation.objects.filter(user_operation__sender=safe)
            .prefetch_related("confirmations")
            .select_related("user_operation")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["safe_address"] = self.kwargs["address"]
        return context

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeOperationWithUserOperationResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeOperationSerializer

    @extend_schema(tags=["4337"])
    def get(self, request, address, *args, **kwargs):
        """
        Returns the list of SafeOperations for a given Safe account
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
        return super().get(request, address, *args, **kwargs)

    @extend_schema(
        tags=["4337"],
        request=serializers.SafeOperationSerializer,
        responses={201: "Created"},
    )
    def post(self, request, address, *args, **kwargs):
        """
        Adds a new SafeOperation for a given Safe account
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


class SafeOperationConfirmationsView(ListCreateAPIView):
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SafeOperationConfirmation.objects.none()

        return SafeOperationConfirmation.objects.filter(
            safe_operation__hash=self.kwargs["safe_operation_hash"]
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["safe_operation_hash"] = self.kwargs.get("safe_operation_hash")
        return context

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeOperationConfirmationResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeOperationConfirmationSerializer

    @extend_schema(
        tags=["4337"],
        responses={
            200: serializers.SafeOperationConfirmationResponseSerializer,
            400: OpenApiResponse(description="Invalid data"),
        },
    )
    def get(self, request, *args, **kwargs):
        """
        Get the list of confirmations for a multisig transaction
        """
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["4337"],
        responses={
            201: OpenApiResponse(description="Created"),
            400: OpenApiResponse(description="Malformed data"),
            422: OpenApiResponse(description="Error processing data"),
        },
    )
    def post(self, request, *args, **kwargs):
        """
        Add a confirmation for a transaction. More than one signature can be used. This endpoint does not support
        the use of delegates to make a transaction trusted.
        """
        return super().post(request, *args, **kwargs)


@extend_schema(tags=["4337"])
class UserOperationView(RetrieveAPIView):
    """
    Returns a UserOperation given its user operation hash
    """

    lookup_field = "hash"
    lookup_url_kwarg = "user_operation_hash"
    queryset = (
        UserOperation.objects.all()
        .select_related("receipt", "safe_operation")
        .prefetch_related("safe_operation__confirmations")
    )
    serializer_class = serializers.UserOperationWithSafeOperationResponseSerializer


class UserOperationsView(ListAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-nonce", "-ethereum_tx__block__timestamp"]
    ordering_fields = ["nonce", "ethereum_tx__block__timestamp"]
    pagination_class = pagination.DefaultPagination
    serializer_class = serializers.UserOperationWithSafeOperationResponseSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return UserOperation.objects.none()

        safe = self.kwargs["address"]
        return (
            UserOperation.objects.filter(sender=safe)
            .select_related("receipt", "safe_operation")
            .prefetch_related("safe_operation__confirmations")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["safe_address"] = self.kwargs["address"]
        return context

    @extend_schema(tags=["4337"])
    def get(self, request, address, *args, **kwargs):
        """
        Returns the list of UserOperations for a given Safe account
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
        return super().get(request, address, *args, **kwargs)
