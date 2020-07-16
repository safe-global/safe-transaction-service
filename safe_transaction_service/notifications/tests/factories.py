import factory

from safe_transaction_service.history.tests.factories import \
    SafeContractFactory

from ..models import FirebaseDevice


class FirebaseDeviceFactory(factory.DjangoModelFactory):
    class Meta:
        model = FirebaseDevice

    safe = factory.SubFactory(SafeContractFactory)
    cloud_messaging_token = factory.faker('isbn13')
    build_number = factory.Sequence()
    bundle = 'company.package.app'
    device_type = 0
    version = factory.Sequence(lambda n: f'{n}.0.0')

