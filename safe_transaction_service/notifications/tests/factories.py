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


class FirebaseDeviceOwnerFactory(DjangoModelFactory):
    class Meta:
        model = FirebaseDeviceOwner

    firebase_device = factory.SubFactory(FirebaseDeviceFactory)
    owner = factory.LazyFunction(lambda: Account.create().address)
