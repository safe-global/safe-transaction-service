from django.shortcuts import get_object_or_404

import django_filters
from djangorestframework_camel_case.parser import CamelCaseJSONParser
from djangorestframework_camel_case.render import CamelCaseJSONRenderer
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import CreateAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.response import Response

from gnosis.eth.utils import fast_is_checksum_address

from . import pagination, serializers
from .models import SafeMessage


class DisableCamelCaseForMessageParser(CamelCaseJSONParser):
    json_underscoreize = {"ignore_fields": ("message",)}


class DisableCamelCaseForMessageRenderer(CamelCaseJSONRenderer):
    json_underscoreize = {"ignore_fields": ("message",)}


class SafeMessageView(RetrieveAPIView):
    lookup_url_kwarg = "message_hash"
    queryset = SafeMessage.objects.prefetch_related("confirmations")
    serializer_class = serializers.SafeMessageResponseSerializer
    renderer_classes = (DisableCamelCaseForMessageRenderer,)


class SafeMessageSignatureView(CreateAPIView):
    serializer_class = serializers.SafeMessageSignatureSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context

        context["safe_message"] = get_object_or_404(
            SafeMessage, pk=self.kwargs["message_hash"]
        )
        return context

    @swagger_auto_schema(
        responses={201: "Created"},
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(status=status.HTTP_201_CREATED)


class SafeMessagesView(ListCreateAPIView):
    filter_backends = [
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    ]
    ordering = ["-created"]
    ordering_fields = ["created", "modified"]
    pagination_class = pagination.DefaultPagination
    parser_classes = (DisableCamelCaseForMessageParser,)
    renderer_classes = (DisableCamelCaseForMessageRenderer,)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context

        context["safe_address"] = self.kwargs["address"]
        return context

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeMessageResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeMessageSerializer

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
        request_body=serializers.SafeMessageSerializer,
        responses={201: "Created"},
    )
    def post(self, request, address, *args, **kwargs):
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
        return SafeMessage.objects.filter(safe=safe).prefetch_related("confirmations")
