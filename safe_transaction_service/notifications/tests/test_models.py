from django.test import TestCase

from eth_account import Account

from safe_transaction_service.history.tests.factories import \
    SafeContractFactory

from ..models import FirebaseDeviceOwner
from .factories import FirebaseDeviceOwnerFactory


class TestFirebaseDeviceOwner(TestCase):
    def test_get_devices_for_safe_and_owners(self):
        safe_contract = SafeContractFactory()
        self.assertEqual(FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
            safe_contract.address, []
        ), [])
        self.assertEqual(FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
            safe_contract.address, [Account.create().address]
        ), [])

        firebase_device_owner = FirebaseDeviceOwnerFactory.create(firebase_device__safes=(safe_contract,))
        firebase_device_owner_2 = FirebaseDeviceOwnerFactory(firebase_device=firebase_device_owner.firebase_device)

        self.assertEqual(
            FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
                Account.create().address,
                []
            ),
            []
        )
        self.assertEqual(
            FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
                safe_contract.address,
                [firebase_device_owner.owner, firebase_device_owner_2.owner]
            ),
            [firebase_device_owner.firebase_device.cloud_messaging_token]
        )

        safe_contract_2 = SafeContractFactory()
        firebase_device_owner_3 = FirebaseDeviceOwnerFactory.create(firebase_device__safes=(safe_contract_2,))
        self.assertEqual(
            FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
                safe_contract.address,
                [firebase_device_owner.owner, firebase_device_owner_2.owner, firebase_device_owner_3.owner]
            ),
            [firebase_device_owner.firebase_device.cloud_messaging_token]
        )
        self.assertEqual(
            FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
                safe_contract_2.address,
                [firebase_device_owner.owner, firebase_device_owner_2.owner, firebase_device_owner_3.owner]
            ),
            [firebase_device_owner_3.firebase_device.cloud_messaging_token]
        )

        firebase_device_owner_3.firebase_device.safes.add(safe_contract)
        self.assertCountEqual(
            FirebaseDeviceOwner.objects.get_devices_for_safe_and_owners(
                safe_contract.address,
                [firebase_device_owner.owner, firebase_device_owner_2.owner, firebase_device_owner_3.owner]
            ),
            [firebase_device_owner.firebase_device.cloud_messaging_token,
             firebase_device_owner_3.firebase_device.cloud_messaging_token]
        )
