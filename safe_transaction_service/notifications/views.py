import logging

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import CreateAPIView, DestroyAPIView
from rest_framework.response import Response

from safe_transaction_service.history.models import SafeContract

from . import serializers
from .models import FirebaseDevice
from .serializers import get_safe_owners

logger = logging.getLogger(__name__)


class FirebaseDeviceCreateView(CreateAPIView):
    """
    Creates a new FirebaseDevice. If uuid is not provided a new device will be created.
    If a uuid for an existing Safe is provided the FirebaseDevice will be updated with all the new data provided.
    Safes provided on the request are always added and never removed/replaced
    Signature must sign `keccack256('gnosis-safe{timestamp-epoch}{uuid}{cloud_messaging_token}{safes_sorted}':
        - `{timestamp-epoch}` must be an integer (no milliseconds)
        - `{safes_sorted}` must be checksummed safe addresses sorted and joined with no spaces
    """

    serializer_class = serializers.FirebaseDeviceSerializer
    response_serializer_class = (
        serializers.FirebaseDeviceSerializerWithOwnersResponseSerializer
    )

    @swagger_auto_schema(
        responses={200: response_serializer_class(), 400: "Invalid data"}
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        response_serializer = self.response_serializer_class(
            data=serializer.validated_data
        )
        response_serializer.is_valid(raise_exception=True)
        headers = self.get_success_headers(response_serializer.data)
        return Response(
            response_serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class FirebaseDeviceDeleteView(DestroyAPIView):
    """
    Remove a FirebaseDevice
    """

    queryset = FirebaseDevice.objects.all()


class FirebaseDeviceSafeDeleteView(DestroyAPIView):
    """
    Remove a Safe for a FirebaseDevice
    """

    queryset = FirebaseDevice.objects.all()

    def perform_destroy(self, firebase_device: FirebaseDevice):
        safe_address = self.kwargs["address"]
        try:
            safe_contract = SafeContract.objects.get(address=safe_address)
            firebase_device.safes.remove(safe_contract)
            current_owners = {
                owner
                for safe in firebase_device.safes.values_list("address", flat=True)
                for owner in get_safe_owners(safe)
            }
            # Remove owners not linked to any Safe
            firebase_device.owners.exclude(owner__in=current_owners).delete()
        except SafeContract.DoesNotExist:
            logger.info(
                "Cannot remove safe=%s for firebase_device with uuid=%s",
                safe_address,
                self.kwargs["pk"],
            )
