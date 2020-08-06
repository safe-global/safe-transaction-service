from typing import Sequence

from rest_framework import serializers

from gnosis.eth.django.serializers import EthereumAddressField

from safe_transaction_service.history.models import SafeContract

from .models import DeviceTypeEnum, FirebaseDevice


class FirebaseDeviceSerializer(serializers.Serializer):
    safes = serializers.ListField(allow_empty=False, child=EthereumAddressField())
    cloud_messaging_token = serializers.CharField(min_length=100, max_length=200)
    build_number = serializers.IntegerField(min_value=0)  # e.g. 1644
    bundle = serializers.CharField(min_length=1, max_length=100)
    device_type = serializers.ChoiceField(choices=[element.name for element in DeviceTypeEnum])
    version = serializers.CharField(min_length=1, max_length=100)  # e.g. 1.0.0-beta

    def validate_safes(self, safes: Sequence[str]):
        safe_contracts = SafeContract.objects.filter(address__in=safes)
        if len(safe_contracts) != len(safes):
            raise serializers.ValidationError("At least one Safe provided was not found")

        return safe_contracts

    def save(self, **kwargs):
        firebase_device, _ = FirebaseDevice.objects.get_or_create(
            cloud_messaging_token=self.validated_data['cloud_messaging_token'],
            defaults={
                'build_number': self.validated_data['build_number'],
                'bundle': self.validated_data['bundle'],
                'device_type': DeviceTypeEnum[self.validated_data['device_type']].value,
                'version': self.validated_data['version'],
            }
        )
        firebase_device.safes.add(self.validated_data['safes'])
        return firebase_device
