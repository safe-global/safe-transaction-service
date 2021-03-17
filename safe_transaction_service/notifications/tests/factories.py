import uuid

import factory
from eth_account import Account
from factory.django import DjangoModelFactory

from ..models import FirebaseDevice, FirebaseDeviceOwner


class FirebaseDeviceFactory(DjangoModelFactory):
    class Meta:
        model = FirebaseDevice

    uuid = factory.LazyFunction(uuid.uuid4)
    cloud_messaging_token = factory.Faker('isbn13')
    build_number = factory.Sequence(lambda n: n)
    bundle = 'company.package.app'
    device_type = 0
    version = factory.Sequence(lambda n: f'{n}.0.0')

    @factory.post_generation
    def safes(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # A list of groups were passed in, use them
            for safe_contract in extracted:
                self.safes.add(safe_contract)


class FirebaseDeviceOwnerFactory(DjangoModelFactory):
    class Meta:
        model = FirebaseDeviceOwner

    firebase_device = factory.SubFactory(FirebaseDeviceFactory)
    owner = factory.LazyFunction(lambda: Account.create().address)
