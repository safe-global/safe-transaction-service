from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.tests.factories import \
    SafeContractFactory
from safe_transaction_service.notifications.models import FirebaseDevice


class TestViews(SafeTestCaseMixin, APITestCase):
    def test_notifications_devices_view(self):
        safe_address = 'invalidaddress'
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        safe_address = Account.create().address
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        safe_contract = SafeContractFactory(address=safe_address)
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(FirebaseDevice.objects.count(), 0)
        data = {
            'cloudMessagingToken': 'A' * 163,
            'buildNumber': 0,
            'bundle': 'company.package.app',
            'deviceType': 'WEB',
            'version': '2.0.1',
        }
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)

        # Same request should not create a new object
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 1)

        # Same request should not create a new object, but changing the token will
        data['cloudMessagingToken'] = 'B' * 163
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)), format='json', data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FirebaseDevice.objects.count(), 2)

        # Use not valid deviceType
        data['deviceType'] = 'RANGER-MORPHER'
        response = self.client.post(reverse('v1:notifications-devices', args=(safe_address,)), format='json', data=data)
        self.assertIn('is not a valid choice', response.content.decode())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(safe_contract.firebase_tokens.count(), 2)
