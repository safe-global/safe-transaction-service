import time
from typing import Any, Dict, List, Sequence, Set, Tuple
from uuid import uuid4

from django.db import IntegrityError, transaction

from eth_typing import ChecksumAddress
from packaging import version as semantic_version
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.eth.django.serializers import EthereumAddressField, HexadecimalField
from gnosis.safe.safe_signature import SafeSignature, SafeSignatureType

from safe_transaction_service.history.models import SafeContract, SafeContractDelegate
from safe_transaction_service.utils.serializers import get_safe_owners

from .models import DeviceTypeEnum, FirebaseDevice, FirebaseDeviceOwner
from .utils import calculate_device_registration_hash


class FirebaseDeviceSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(default=uuid4)  # TODO Make it required
    safes = serializers.ListField(allow_empty=False, child=EthereumAddressField())
    cloud_messaging_token = serializers.CharField(min_length=100, max_length=200)
    build_number = serializers.IntegerField(min_value=0)  # e.g. 1644
    bundle = serializers.CharField(min_length=1, max_length=100)
    device_type = serializers.ChoiceField(
        choices=[element.name for element in DeviceTypeEnum]
    )
    version = serializers.CharField(min_length=1, max_length=100)  # e.g. 1.0.0-beta
    timestamp = serializers.IntegerField(required=False)  # TODO Make it required
    signatures = serializers.ListField(
        required=False,
        child=HexadecimalField(
            required=False, min_length=65, max_length=65
        ),  # Signatures must be 65 bytes
    )

    def validate_safes(
        self, safes: Sequence[ChecksumAddress]
    ) -> Sequence[ChecksumAddress]:
        if SafeContract.objects.filter(address__in=safes).count() != len(safes):
            raise serializers.ValidationError(
                "At least one Safe provided was not found or is duplicated"
            )
        return safes

    def validate_timestamp(self, timestamp: int) -> int:
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
                raise ValidationError(
                    f"Provided timestamp is not in a range within {minutes_allowed} minutes"
                )
        return timestamp

    def validate_version(self, value: str) -> str:
        try:
            semantic_version.Version(value)
        except semantic_version.InvalidVersion:
            raise serializers.ValidationError("Semantic version was expected")
        return value

    def get_valid_owners(
        self, safe_addresses: Sequence[ChecksumAddress]
    ) -> Set[ChecksumAddress]:
        """
        Return safe owners and delegates

        :param safe_addresses:
        :return:
        """
        valid_owners = set()
        for safe_address in safe_addresses:
            owners = get_safe_owners(safe_address)
            delegates = SafeContractDelegate.objects.get_delegates_for_safe_and_owners(
                safe_address, owners
            )
            valid_owners = valid_owners.union(owners, delegates)

        return valid_owners

    def process_parsed_signatures(
        self,
        safe_owners: Sequence[ChecksumAddress],
        signatures: Sequence[bytes],
        hash_to_sign: bytes,
    ) -> Tuple[List[ChecksumAddress], List[ChecksumAddress]]:
        """
        :param safe_owners: Current owners of the Safe
        :param signatures: List of signatures for registration
        :param hash_to_sign: Raw hash or EIP191 encoded registration authorization hash is accepted
        :return: A tuple with ``accepted owners to register`` and ``not accepted owners``
        """
        owners_to_register = []  # Owners to register for notifications
        owners_to_not_register = []  # Owners of the Safe not present in the signature
        for signature in signatures:
            parsed_signatures = SafeSignature.parse_signature(signature, hash_to_sign)
            if not parsed_signatures:
                raise ValidationError("Signature cannot be parsed")
            for safe_signature in parsed_signatures:
                if (
                    safe_signature.signature_type != SafeSignatureType.EOA
                    or not safe_signature.is_valid()
                ):
                    raise ValidationError(
                        "An externally owned account signature was expected"
                    )
                owner = safe_signature.owner
                if owner in (owners_to_register + owners_to_not_register):
                    raise ValidationError(f"Signature for owner={owner} is duplicated")

                if owner in safe_owners:
                    owners_to_register.append(owner)
                else:
                    owners_to_not_register.append(owner)
                    # raise ValidationError(f'Owner={owner} is not an owner of any of the safes={data["safes"]}. '
                    #                       f'Expected hash to sign {hash_to_sign.hex()}')
        return owners_to_register, owners_to_not_register

    def validate(self, attrs: Dict[str, Any]):
        attrs = super().validate(attrs)
        signatures = attrs.get("signatures") or []
        safe_addresses = attrs["safes"]
        owners_to_register, owners_to_not_register = [], []
        if signatures:
            safe_owners = self.get_valid_owners(safe_addresses)
            # Allow 2 valid hashes, raw hash and EIP191 one
            hash_raw_to_sign = calculate_device_registration_hash(
                attrs["timestamp"],
                attrs["uuid"],
                attrs["cloud_messaging_token"],
                attrs["safes"],
            )
            hash_eip191_to_sign = calculate_device_registration_hash(
                attrs["timestamp"],
                attrs["uuid"],
                attrs["cloud_messaging_token"],
                attrs["safes"],
                eip191=True,
            )
            for hash_to_sign in (hash_raw_to_sign, hash_eip191_to_sign):
                # We will check the 2 accepted hashes, EIP191 and raw one. If we find valid owners, stop
                (
                    owners_to_register,
                    owners_to_not_register,
                ) = self.process_parsed_signatures(
                    safe_owners, signatures, hash_to_sign
                )
                if owners_to_register:
                    break

            if len(signatures) > len(owners_to_register + owners_to_not_register):
                raise ValidationError(
                    "Number of signatures is less than the number of owners detected"
                )

        attrs["owners_registered"] = owners_to_register
        attrs["owners_not_registered"] = owners_to_not_register
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        try:
            uuid = self.validated_data["uuid"]
            firebase_device, _ = FirebaseDevice.objects.update_or_create(
                uuid=uuid,
                defaults={
                    "cloud_messaging_token": self.validated_data[
                        "cloud_messaging_token"
                    ],
                    "build_number": self.validated_data["build_number"],
                    "bundle": self.validated_data["bundle"],
                    "device_type": DeviceTypeEnum[
                        self.validated_data["device_type"]
                    ].value,
                    "version": self.validated_data["version"],
                },
            )
        except IntegrityError:
            raise serializers.ValidationError(
                "Cloud messaging token is linked to another device"
            )

        # Remove every owner registered for the device and add the provided ones
        firebase_device.owners.all().delete()
        for owner in self.validated_data["owners_registered"]:
            try:
                FirebaseDeviceOwner.objects.create(
                    firebase_device=firebase_device, owner=owner
                )
            except IntegrityError:
                raise serializers.ValidationError(
                    f"Owner {owner} already created for firebase_device"
                )

        # Remove every Safe registered for the device and add the provided ones
        firebase_device.safes.clear()
        safe_contracts = SafeContract.objects.filter(
            address__in=self.validated_data["safes"]
        )
        firebase_device.safes.add(*safe_contracts)
        return firebase_device


class FirebaseDeviceSerializerWithOwnersResponseSerializer(FirebaseDeviceSerializer):
    owners_registered = serializers.ListField(
        allow_empty=True, child=EthereumAddressField()
    )
    owners_not_registered = serializers.ListField(
        allow_empty=True, child=EthereumAddressField()
    )
