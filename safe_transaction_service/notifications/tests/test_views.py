import uuid

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.tests.factories import \
    SafeContractFactory
from safe_transaction_service.notifications.models import FirebaseDevice

from .factories import FirebaseDeviceFactory


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_notifications_devices_create_view(self):
        response = self.client.post(reverse('v1:notifications-devices'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        safe_address = Account.create().address
        safe_contract = SafeContractFactory(address=safe_address)

        self.assertEqual(FirebaseDevice.objects.count(), 0)
        data = {
            'safes': [safe_address],
            'cloudMessagingToken': 'A' * 163,
            'buildNumber': 0,
            'bundle': 'company.package.app',
            'deviceType': 'WEB',
            'version': '2.0.1',
        }
        response = self.client.post(reverse('v1:notifications-devices'), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)
        device_uuid = response.data['uuid']
        self.assertTrue(uuid.UUID(device_uuid))

        # Same request should return a 400 because a new device with same push token cannot be created
        response = self.client.post(reverse('v1:notifications-devices'), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Request with `uuid` should not create a new object
        data['uuid'] = device_uuid
        response = self.client.post(reverse('v1:notifications-devices'), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)

        # Changing the token and using the uuid will change the cloud messaging token
        data['cloudMessagingToken'] = 'B' * 163
        response = self.client.post(reverse('v1:notifications-devices'), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)
        self.assertEqual(FirebaseDevice.objects.first().cloud_messaging_token, data['cloudMessagingToken'])

        # Add the same FirebaseDevice to another Safe
        another_safe_contract = SafeContractFactory()
        another_safe_address = another_safe_contract.address
        data['safes'] += [another_safe_address]
        response = self.client.post(reverse('v1:notifications-devices'), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(safe_contract.firebase_devices.count(), 1)
        self.assertEqual(another_safe_contract.firebase_devices.count(), 1)
        self.assertEqual(FirebaseDevice.objects.count(), 1)
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 2)

        # Use not valid deviceType
        data['deviceType'] = 'RANGER-MORPHER'
        response = self.client.post(reverse('v1:notifications-devices'), format='json', data=data)
        self.assertIn('is not a valid choice', response.content.decode())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(safe_contract.firebase_devices.count(), 1)

    def test_notifications_devices_delete_view(self):
        safe_contract = SafeContractFactory()
        firebase_device = FirebaseDeviceFactory()
        firebase_device.safes.add(safe_contract)
        device_id = firebase_device.uuid

        self.assertEqual(FirebaseDevice.objects.count(), 1)
        response = self.client.delete(reverse('v1:notifications-devices-delete', args=(device_id,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(FirebaseDevice.objects.count(), 0)

        # Try to delete again if not exists
        response = self.client.delete(reverse('v1:notifications-devices-delete', args=(device_id,)), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_notifications_devices_safe_delete_view(self):
        safe_contract = SafeContractFactory()
        firebase_device = FirebaseDeviceFactory()
        firebase_device.safes.add(safe_contract)
        device_id = firebase_device.uuid

        # Test not existing `safe_contract`, even if `device_id` is correct
        random_safe_address = Account.create().address
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 1)
        response = self.client.delete(reverse('v1:notifications-devices-safes-delete',
                                              args=(device_id, random_safe_address)), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 1)

        # Happy path
        response = self.client.delete(reverse('v1:notifications-devices-safes-delete',
                                              args=(device_id, safe_contract.address)), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 0)

        # Try to delete again and get the same result even if the Safe is not linked
        response = self.client.delete(reverse('v1:notifications-devices-safes-delete',
                                              args=(device_id, safe_contract.address)), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 0)

        # Remove not existing Safe should not trigger an error
        response = self.client.delete(reverse('v1:notifications-devices-safes-delete',
                                              args=(device_id, Account.create().address)), format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(FirebaseDevice.objects.first().safes.count(), 0)
