import uuid
from typing import Sequence

from django.db import IntegrityError

from packaging import version as semantic_version
from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField

from safe_transaction_service.history.models import SafeContract

from .models import DeviceTypeEnum, FirebaseDevice


class FirebaseDeviceSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(default=uuid.uuid4)
    safes = serializers.ListField(allow_empty=False, child=EthereumAddressField())
    cloud_messaging_token = serializers.CharField(min_length=100, max_length=200)
    build_number = serializers.IntegerField(min_value=0)  # e.g. 1644
    bundle = serializers.CharField(min_length=1, max_length=100)
    device_type = serializers.ChoiceField(choices=[element.name for element in DeviceTypeEnum])
    version = serializers.CharField(min_length=1, max_length=100)  # e.g. 1.0.0-beta

    def validate_safes(self, safes: Sequence[str]):
        if SafeContract.objects.filter(address__in=safes).count() != len(safes):
            raise serializers.ValidationError('At least one Safe provided was not found')
        return safes

    def validate_version(self, value: str):
        try:
            semantic_version.Version(value)
        except semantic_version.InvalidVersion:
            raise serializers.ValidationError('Semantic version was expected')
        return value

    def save(self, **kwargs):
        try:
            firebase_device, _ = FirebaseDevice.objects.update_or_create(
                uuid=self.validated_data['uuid'],
                defaults={
                    'cloud_messaging_token': self.validated_data['cloud_messaging_token'],
                    'build_number': self.validated_data['build_number'],
                    'bundle': self.validated_data['bundle'],
                    'device_type': DeviceTypeEnum[self.validated_data['device_type']].value,
                    'version': self.validated_data['version'],
                }
            )
        except IntegrityError:
            raise serializers.ValidationError('Cloud messaging token is linked to another device')
        safe_contracts = SafeContract.objects.filter(address__in=self.validated_data['safes'])
        firebase_device.safes.add(*safe_contracts)
        return firebase_device
