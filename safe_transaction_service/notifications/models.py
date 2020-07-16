from enum import Enum

from django.db import models

from safe_transaction_service.history.models import SafeContract


class DeviceTypeEnum(Enum):
    ANDROID = 0
    IOS = 1
    WEB = 2


class FirebaseDevice(models.Model):
    safe = models.ForeignKey(SafeContract, on_delete=models.CASCADE, related_name='firebase_tokens')
    cloud_messaging_token = models.CharField(max_length=200)  # Token length should be 163
    build_number = models.PositiveIntegerField(default=0)  # e.g. 1644
    bundle = models.CharField(max_length=100, default='')
    device_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in DeviceTypeEnum])
    version = models.CharField(max_length=50, default='')  # e.g 1.0.0

    class Meta:
        verbose_name = 'Firebase Device'
        verbose_name_plural = 'Firebase Devices'
        unique_together = (('safe', 'cloud_messaging_token'),)

    def __str__(self):
        token = self.cloud_messaging_token[:10] if self.cloud_messaging_token else 'No Token'
        device_name = DeviceTypeEnum(self.device_type).name
        return f'{self.safe_id} - {device_name} {self.version} - {token}...'



