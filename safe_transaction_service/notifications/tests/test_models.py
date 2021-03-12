from django.test import TestCase

from eth_account import Account

from ..models import FirebaseDeviceOwner
from .factories import FirebaseDeviceOwnerFactory


class TestFirebaseDeviceOwner(TestCase):
    def test_get_devices_for_owners(self):
        self.assertEqual(FirebaseDeviceOwner.objects.get_devices_for_owners([]), [])
        self.assertEqual(FirebaseDeviceOwner.objects.get_devices_for_owners([Account.create().address]), [])

        firebase_device_owner = FirebaseDeviceOwnerFactory()
        firebase_device_owner_2 = FirebaseDeviceOwnerFactory(firebase_device=firebase_device_owner.firebase_device)
        self.assertEqual(
            FirebaseDeviceOwner.objects.get_devices_for_owners(
                [firebase_device_owner.owner, firebase_device_owner_2.owner]
            ),
            [firebase_device_owner.firebase_device.cloud_messaging_token]
        )

        firebase_device_owner_3 = FirebaseDeviceOwnerFactory()
        self.assertEqual(
            FirebaseDeviceOwner.objects.get_devices_for_owners(
                [firebase_device_owner.owner, firebase_device_owner_2.owner]
            ),
            [firebase_device_owner.firebase_device.cloud_messaging_token]
        )
        self.assertCountEqual(
            FirebaseDeviceOwner.objects.get_devices_for_owners(
                [firebase_device_owner.owner, firebase_device_owner_2.owner, firebase_device_owner_3.owner]
            ),
            [firebase_device_owner.firebase_device.cloud_messaging_token,
             firebase_device_owner_3.firebase_device.cloud_messaging_token]
        )
