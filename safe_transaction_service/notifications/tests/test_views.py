import time
import uuid
from unittest import mock

from django.urls import reverse

from eth_account import Account
from eth_account.messages import encode_defunct
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.tests.factories import (
    SafeContractDelegateFactory,
    SafeContractFactory,
)
from safe_transaction_service.notifications.models import (
    FirebaseDevice,
    FirebaseDeviceOwner,
)

from ..utils import calculate_device_registration_hash
from .factories import FirebaseDeviceFactory, FirebaseDeviceOwnerFactory


class TestNotificationViews(SafeTestCaseMixin, APITestCase):
    def test_notifications_devices_create_view(self):
        response = self.client.post(reverse("v1:notifications:devices"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_address = Account.create().address
        safe_contract = SafeContractFactory(address=safe_address)

        self.assertEqual(FirebaseDevice.objects.count(), 0)
        data = {
            "safes": [safe_address],
            "cloudMessagingToken": "A" * 163,
            "buildNumber": 0,
            "bundle": "company.package.app",
            "deviceType": "WEB",
            "version": "2.0.1",
        }
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)
        device_uuid = response.data["uuid"]
        self.assertTrue(uuid.UUID(device_uuid))

        # Same request should return a 400 because a new device with same push token cannot be created
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Request with `uuid` should not create a new object
        data["uuid"] = device_uuid
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)

        # Changing the token and using the uuid will change the cloud messaging token
        data["cloudMessagingToken"] = "B" * 163
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)
        self.assertEqual(
            FirebaseDevice.objects.first().cloud_messaging_token,
            data["cloudMessagingToken"],
        )

        # Add the same FirebaseDevice to another Safe
        safe_contract_2 = SafeContractFactory()
        data["safes"].append(safe_contract_2.address)
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(safe_contract.firebase_devices.count(), 1)
        self.assertEqual(safe_contract_2.firebase_devices.count(), 1)
        self.assertEqual(FirebaseDevice.objects.count(), 1)
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 2)

        # Use not valid deviceType
        previous_device_type = data["deviceType"]
        data["deviceType"] = "RANGER-MORPHER"
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertIn("is not a valid choice", response.content.decode())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(safe_contract.firebase_devices.count(), 1)
        data["deviceType"] = previous_device_type

        # Use not valid version
        previous_version = data["version"]
        data["version"] = "Megazord"
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertIn("Semantic version was expected", response.content.decode())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(safe_contract.firebase_devices.count(), 1)
        data["version"] = previous_version

        # Remove one of the Safes
        data["safes"] = [safe_contract_2.address]
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(safe_contract.firebase_devices.count(), 0)
        self.assertEqual(safe_contract_2.firebase_devices.count(), 1)

    def test_notifications_devices_create_with_signatures_view(self):
        safe_address = Account.create().address
        safe_contract = SafeContractFactory(address=safe_address)
        owner_account = Account.create()
        owner_account_2 = Account.create()

        self.assertEqual(FirebaseDevice.objects.count(), 0)
        unique_id = uuid.uuid4()
        timestamp = int(time.time())
        cloud_messaging_token = "A" * 163
        safes = [safe_address]
        hash_to_sign = calculate_device_registration_hash(
            timestamp, unique_id, cloud_messaging_token, safes
        )
        signatures = [owner_account.signHash(hash_to_sign)["signature"].hex()]
        data = {
            "uuid": unique_id,
            "safes": safes,
            "cloudMessagingToken": cloud_messaging_token,
            "buildNumber": 0,
            "bundle": "company.package.app",
            "deviceType": "WEB",
            "version": "2.0.1",
            "timestamp": timestamp,
            "signatures": signatures,
        }
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            f"Could not get Safe {safe_address} owners from blockchain, check contract exists on network",
            response.data["non_field_errors"][0],
        )

        with mock.patch(
            "safe_transaction_service.notifications.serializers.get_safe_owners",
            return_value=[owner_account.address],
        ):
            response = self.client.post(
                reverse("v1:notifications:devices"), format="json", data=data
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["uuid"], str(unique_id))
            self.assertEqual(FirebaseDevice.objects.count(), 1)
            self.assertEqual(FirebaseDeviceOwner.objects.count(), 1)
            self.assertEqual(
                FirebaseDeviceOwner.objects.first().owner, owner_account.address
            )

            # Add another signature
            signatures.append(owner_account_2.signHash(hash_to_sign)["signature"].hex())
            response = self.client.post(
                reverse("v1:notifications:devices"), format="json", data=data
            )
            # self.assertIn('is not an owner of any of the safes', str(response.data['non_field_errors']))
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(
                response.data["owners_registered"], [owner_account.address]
            )
            self.assertEqual(
                response.data["owners_not_registered"], [owner_account_2.address]
            )

        with mock.patch(
            "safe_transaction_service.notifications.serializers.get_safe_owners",
            return_value=[owner_account.address, owner_account_2.address],
        ):
            response = self.client.post(
                reverse("v1:notifications:devices"), format="json", data=data
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(
                response.data["owners_registered"],
                [owner_account.address, owner_account_2.address],
            )
            self.assertEqual(response.data["owners_not_registered"], [])
            self.assertEqual(FirebaseDevice.objects.count(), 1)
            self.assertCountEqual(
                FirebaseDeviceOwner.objects.values_list("owner", flat=True),
                [owner_account.address, owner_account_2.address],
            )

    def test_notifications_devices_create_with_signatures_eip191_view(self):
        safe_address = Account.create().address
        safe_contract = SafeContractFactory(address=safe_address)
        owner_account = Account.create()
        owner_account_2 = Account.create()

        self.assertEqual(FirebaseDevice.objects.count(), 0)
        unique_id = uuid.uuid4()
        timestamp = int(time.time())
        cloud_messaging_token = "A" * 163
        safes = [safe_address]
        hash_to_sign = calculate_device_registration_hash(
            timestamp, unique_id, cloud_messaging_token, safes
        )
        message_to_sign = encode_defunct(hash_to_sign)
        signatures = [owner_account.sign_message(message_to_sign)["signature"].hex()]
        data = {
            "uuid": unique_id,
            "safes": safes,
            "cloudMessagingToken": cloud_messaging_token,
            "buildNumber": 0,
            "bundle": "company.package.app",
            "deviceType": "WEB",
            "version": "2.0.1",
            "timestamp": timestamp,
            "signatures": signatures,
        }

        with mock.patch(
            "safe_transaction_service.notifications.serializers.get_safe_owners",
            return_value=[owner_account.address],
        ):
            response = self.client.post(
                reverse("v1:notifications:devices"), format="json", data=data
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["uuid"], str(unique_id))
            self.assertEqual(FirebaseDevice.objects.count(), 1)
            self.assertEqual(FirebaseDeviceOwner.objects.count(), 1)
            self.assertEqual(
                FirebaseDeviceOwner.objects.first().owner, owner_account.address
            )

    def test_notifications_devices_create_with_delegates_signatures_view(self):
        delegate = Account.create()
        safe_contract_delegate = SafeContractDelegateFactory(delegate=delegate.address)
        safe_address = safe_contract_delegate.safe_contract.address

        self.assertEqual(FirebaseDevice.objects.count(), 0)
        unique_id = uuid.uuid4()
        timestamp = int(time.time())
        cloud_messaging_token = "A" * 163
        safes = [safe_address]
        hash_to_sign = calculate_device_registration_hash(
            timestamp, unique_id, cloud_messaging_token, safes
        )
        signatures = [delegate.signHash(hash_to_sign)["signature"].hex()]
        data = {
            "uuid": unique_id,
            "safes": [safe_address],
            "cloudMessagingToken": cloud_messaging_token,
            "buildNumber": 0,
            "bundle": "company.package.app",
            "deviceType": "WEB",
            "version": "2.0.1",
            "timestamp": timestamp,
            "signatures": signatures,
        }
        response = self.client.post(
            reverse("v1:notifications:devices"), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            f"Could not get Safe {safe_address} owners from blockchain, check contract exists on network",
            response.data["non_field_errors"][0],
        )

        with mock.patch(
            "safe_transaction_service.notifications.serializers.get_safe_owners",
            return_value=[safe_contract_delegate.delegator],
        ):
            response = self.client.post(
                reverse("v1:notifications:devices"), format="json", data=data
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["owners_registered"], [delegate.address])
            self.assertEqual(response.data["owners_not_registered"], [])
            self.assertEqual(
                FirebaseDeviceOwner.objects.filter(owner=delegate.address).count(), 1
            )

    def test_notifications_devices_delete_view(self):
        safe_contract = SafeContractFactory()
        firebase_device = FirebaseDeviceFactory()
        firebase_device.safes.add(safe_contract)
        device_id = firebase_device.uuid
        FirebaseDeviceOwnerFactory(firebase_device=firebase_device)

        self.assertEqual(FirebaseDevice.objects.count(), 1)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 1)
        response = self.client.delete(
            reverse("v1:notifications:devices-delete", args=(device_id,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(FirebaseDevice.objects.count(), 0)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 0)

        # Try to delete again if not exists
        response = self.client.delete(
            reverse("v1:notifications:devices-delete", args=(device_id,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_notifications_devices_safe_delete_view(self):
        safe_contract = SafeContractFactory()
        firebase_device = FirebaseDeviceFactory()
        firebase_device_owner = FirebaseDeviceOwnerFactory(
            firebase_device=firebase_device
        )
        not_related_firebase_device_owner = FirebaseDeviceOwnerFactory()
        firebase_device.safes.add(safe_contract)
        device_id = firebase_device.uuid

        # Test not existing `safe_contract`, even if `device_id` is correct
        random_safe_address = Account.create().address
        self.assertEqual(firebase_device.safes.count(), 1)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 2)
        response = self.client.delete(
            reverse(
                "v1:notifications:devices-safes-delete",
                args=(device_id, random_safe_address),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(firebase_device.safes.count(), 1)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 2)

        # Happy path
        response = self.client.delete(
            reverse(
                "v1:notifications:devices-safes-delete",
                args=(device_id, safe_contract.address),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(firebase_device.safes.count(), 0)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 1)
        self.assertEqual(
            FirebaseDeviceOwner.objects.get(), not_related_firebase_device_owner
        )

        # Try to delete again and get the same result even if the Safe is not linked
        response = self.client.delete(
            reverse(
                "v1:notifications:devices-safes-delete",
                args=(device_id, safe_contract.address),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(firebase_device.safes.count(), 0)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 1)

        # Remove not existing Safe should not trigger an error
        response = self.client.delete(
            reverse(
                "v1:notifications:devices-safes-delete",
                args=(device_id, Account.create().address),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(firebase_device.safes.count(), 0)
        self.assertEqual(FirebaseDeviceOwner.objects.count(), 1)
