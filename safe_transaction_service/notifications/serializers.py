import time
import uuid
from typing import Any, Dict, Sequence

from django.db import IntegrityError

from hexbytes import HexBytes
from packaging import version as semantic_version
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from web3 import Web3

from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField)
from gnosis.safe.safe_signature import SafeSignature

from safe_transaction_service.history.models import SafeContract

from .models import DeviceTypeEnum, FirebaseDevice
from .utils import get_safe_owners


class FirebaseDeviceSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(default=uuid.uuid4)  # TODO Make it required
    safes = serializers.ListField(allow_empty=False, child=EthereumAddressField())
    cloud_messaging_token = serializers.CharField(min_length=100, max_length=200)
    build_number = serializers.IntegerField(min_value=0)  # e.g. 1644
    bundle = serializers.CharField(min_length=1, max_length=100)
    device_type = serializers.ChoiceField(choices=[element.name for element in DeviceTypeEnum])
    version = serializers.CharField(min_length=1, max_length=100)  # e.g. 1.0.0-beta
    timestamp = serializers.IntegerField(required=False)  # TODO Make it required
    signatures = serializers.ListField(
        required=False,
        child=HexadecimalField(required=False, min_length=130)  # Signatures must be at least 65 bytes
    )

    def _calculate_hash(self, timestamp: int, identifier: uuid.UUID, cloud_messaging_token: str,
                        safes: Sequence[str], prefix: str = 'gnosis-safe') -> HexBytes:

        safes_to_str = ''.join(sorted(safes))
        str_to_sign = f'{prefix}{timestamp}{identifier}{cloud_messaging_token}{safes_to_str}'
        return Web3.keccak(text=str_to_sign)

    def validate_safes(self, safes: Sequence[str]):
        if SafeContract.objects.filter(address__in=safes).count() != len(safes):
            raise serializers.ValidationError('At least one Safe provided was not found')
        return safes

    def validate_timestamp(self, timestamp: int):
        """
        Validate if timestamp is not on the future or older than 5 minutes
        :param timestamp:
        :return:
        """
        if timestamp is not None:
            minutes_allowed = 5
            current_epoch = int(time.time())
            time_delta = current_epoch - timestamp
            if time_delta < 0:  # Timestamp on the future
                raise ValidationError('Provided timestamp is on the future')
            elif time_delta > (60 * minutes_allowed):  # Timestamp older than 5 minutes
                raise ValidationError(f'Provided timestamp is older than {minutes_allowed} minutes')
        return timestamp

    def validate_version(self, value: str):
        try:
            semantic_version.Version(value)
        except semantic_version.InvalidVersion:
            raise serializers.ValidationError('Semantic version was expected')
        return value

    def validate(self, data: Dict[str, Any]):
        data = super().validate(data)
        data['owners'] = {}
        signatures = data.get('signatures') or []
        if signatures:
            current_owners = {owner for safe in data['safes'] for owner in get_safe_owners(safe)}
            for signature in signatures:
                hash_to_sign = self._calculate_hash(data['timestamp'], data['uuid'], data['cloud_messaging_token'],
                                                    data['safes'])
                parsed_signatures = SafeSignature.parse_signature(signature, hash_to_sign)
                for safe_signature in parsed_signatures:
                    if (owner := safe_signature.owner) in current_owners:
                        data['owners'].add(owner)
        return data

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
