from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import DeviceTypeEnum, FirebaseDevice


class FirebaseDeviceSerializer(serializers.Serializer):
    cloud_messaging_token = serializers.CharField(min_length=100)
    build_number = serializers.IntegerField(min_value=0)  # e.g. 1644
    bundle = serializers.CharField(min_length=1, max_length=100)
    device_type = serializers.ChoiceField(choices=[element.name for element in DeviceTypeEnum])
    version = serializers.CharField(min_length=1, max_length=100)  # e.g. 1.0.0-beta

    def validate_device_type(self, device_type: str):
        if not hasattr(DeviceTypeEnum, device_type):
            raise ValidationError('Client must be one of %s' % [d.name for d in DeviceTypeEnum])

        return DeviceTypeEnum[device_type]

    def validate(self, data):
        data = super().validate(data)
        return data

    def save(self, **kwargs):
        firebase_device, _ = FirebaseDevice.objects.get_or_create(
            safe_id=self.context['safe'],
            cloud_messaging_token=self.validated_data['cloud_messaging_token'],
            defaults={
                'build_number': self.validated_data['build_number'],
                'bundle': self.validated_data['bundle'],
                'device_type': DeviceTypeEnum[self.validated_data['device_type']].value,
                'version': self.validated_data['version'],
            }
        )
        return firebase_device
