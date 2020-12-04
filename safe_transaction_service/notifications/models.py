import uuid
from enum import Enum

from django.db import models

from gnosis.eth.django.models import EthereumAddressField

from safe_transaction_service.history.models import SafeContract


class DeviceTypeEnum(Enum):
    ANDROID = 0
    IOS = 1
    WEB = 2


class FirebaseDevice(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    safes = models.ManyToManyField(SafeContract, related_name='firebase_devices')
    cloud_messaging_token = models.CharField(null=True, unique=True, max_length=200)  # Token length should be 163
    build_number = models.PositiveIntegerField(default=0)  # e.g. 1644
    bundle = models.CharField(max_length=100, default='')
    device_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in DeviceTypeEnum])
    version = models.CharField(max_length=50, default='')  # e.g 1.0.0

    class Meta:
        verbose_name = 'Firebase Device'
        verbose_name_plural = 'Firebase Devices'

    def __str__(self):
        token = self.cloud_messaging_token[:10] if self.cloud_messaging_token else 'No Token'
        device_name = DeviceTypeEnum(self.device_type).name
        return f'{device_name} {self.version} - {token}...'


class FirebaseDeviceOwner(models.Model):
    firebase_device = models.ForeignKey(FirebaseDevice, on_delete=models.CASCADE, related_name='owners')
    owner = EthereumAddressField(db_index=True)

    class Meta:
        verbose_name = 'Firebase Device Owner'
        verbose_name_plural = 'Firebase Device Owners'
        unique_together = (('firebase_device', 'owner'),)

    def __str__(self):
        return f'{self.owner} for device {self.firebase_device_id}'
