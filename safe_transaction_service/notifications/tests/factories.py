import uuid

import factory
from factory.django import DjangoModelFactory

from ..models import FirebaseDevice


class FirebaseDeviceFactory(DjangoModelFactory):
    class Meta:
        model = FirebaseDevice

    uuid = factory.LazyFunction(uuid.uuid4)
    cloud_messaging_token = factory.Faker('isbn13')
    build_number = factory.Sequence(lambda n: n)
    bundle = 'company.package.app'
    device_type = 0
    version = factory.Sequence(lambda n: f'{n}.0.0')
