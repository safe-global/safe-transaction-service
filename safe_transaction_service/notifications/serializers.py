import time
from typing import Any, Dict, Sequence
from uuid import uuid4

from django.db import IntegrityError

from packaging import version as semantic_version
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField)
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.history.models import SafeContract

from .models import DeviceTypeEnum, FirebaseDevice, FirebaseDeviceOwner
from .utils import calculate_device_registration_hash, get_safe_owners


class FirebaseDeviceSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(default=uuid4)  # TODO Make it required
    safes = serializers.ListField(allow_empty=False, child=EthereumAddressField())
    cloud_messaging_token = serializers.CharField(min_length=100, max_length=200)
    build_number = serializers.IntegerField(min_value=0)  # e.g. 1644
    bundle = serializers.CharField(min_length=1, max_length=100)
    device_type = serializers.ChoiceField(choices=[element.name for element in DeviceTypeEnum])
    version = serializers.CharField(min_length=1, max_length=100)  # e.g. 1.0.0-beta
    timestamp = serializers.IntegerField(required=False)  # TODO Make it required
    signatures = serializers.ListField(
        required=False,
        child=HexadecimalField(required=False, min_length=65, max_length=65)  # Signatures must be 65 bytes
    )

    def validate_safes(self, safes: Sequence[str]):
        if SafeContract.objects.filter(address__in=safes).count() != len(safes):
            raise serializers.ValidationError('At least one Safe provided was not found or is duplicated')
        return safes

    def validate_timestamp(self, timestamp: int):
        """
        Validate if timestamp is not on a range within 5 minutes
        :param timestamp:
        :return:
        """
        if timestamp is not None:
            minutes_allowed = 5
            current_epoch = int(time.time())
            time_delta = abs(current_epoch - timestamp)
            if time_delta > (60 * minutes_allowed):  # Timestamp older than 5 minutes
                raise ValidationError(f'Provided timestamp is not in a range within {minutes_allowed} minutes')
        return timestamp

    def validate_version(self, value: str):
        try:
            semantic_version.Version(value)
        except semantic_version.InvalidVersion:
            raise serializers.ValidationError('Semantic version was expected')
        return value

    def validate(self, data: Dict[str, Any]):
        data = super().validate(data)
        signature_owners = []
        owners_without_safe = []
        signatures = data.get('signatures') or []
        if signatures:
            current_owners = {owner for safe in data['safes'] for owner in get_safe_owners(safe)}
            for signature in signatures:
                hash_to_sign = calculate_device_registration_hash(data['timestamp'],
                                                                  data['uuid'],
                                                                  data['cloud_messaging_token'],
                                                                  data['safes'])
                parsed_signatures = SafeSignature.parse_signature(signature, hash_to_sign)
                if not parsed_signatures:
                    raise ValidationError('Signature cannot be parsed')
                for safe_signature in parsed_signatures:
                    if safe_signature.signature_type != SafeSignatureType.EOA or not safe_signature.is_valid():
                        raise ValidationError('An externally owned account signature was expected')
                    owner = safe_signature.owner
                    if owner in (signature_owners + owners_without_safe):
                        raise ValidationError(f'Signature for owner={owner} is duplicated')
                    elif owner not in current_owners:
                        owners_without_safe.append(owner)
                        # raise ValidationError(f'Owner={owner} is not an owner of any of the safes={data["safes"]}. '
                        #                       f'Expected hash to sign {hash_to_sign.hex()}')
                    else:
                        signature_owners.append(owner)
            if len(signatures) > len(signature_owners + owners_without_safe):
                raise ValidationError('Number of signatures is less than the number of owners detected')

        data['owners_registered'] = signature_owners
        data['owners_not_registered'] = owners_without_safe
        return data

    def save(self, **kwargs):
        try:
            uuid = self.validated_data['uuid']
            firebase_device, _ = FirebaseDevice.objects.update_or_create(
                uuid=uuid,
                defaults={
                    'cloud_messaging_token': self.validated_data['cloud_messaging_token'],
                    'build_number': self.validated_data['build_number'],
                    'bundle': self.validated_data['bundle'],
                    'device_type': DeviceTypeEnum[self.validated_data['device_type']].value,
                    'version': self.validated_data['version'],
                }
            )
        except IntegrityError as e:
            raise serializers.ValidationError('Cloud messaging token is linked to another device')

        # Remove every owner registered for the device and add the provided ones
        firebase_device.owners.all().delete()
        for owner in self.validated_data['owners_registered']:
            FirebaseDeviceOwner.objects.create(
                firebase_device=firebase_device,
                owner=owner
            )

        # Remove every Safe registered for the device and add the provided ones
        firebase_device.safes.clear()
        safe_contracts = SafeContract.objects.filter(address__in=self.validated_data['safes'])
        firebase_device.safes.add(*safe_contracts)
        return firebase_device


class FirebaseDeviceSerializerWithOwnersResponseSerializer(FirebaseDeviceSerializer):
    owners_registered = serializers.ListField(allow_empty=True, child=EthereumAddressField())
    owners_not_registered = serializers.ListField(allow_empty=True, child=EthereumAddressField())
