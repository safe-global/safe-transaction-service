import factory

from ..models import FirebaseDevice
from safe_transaction_service.history.tests.factories import SafeContractFactory


class FirebaseDeviceFactory(factory.DjangoModelFactory):
    class Meta:
        model = FirebaseDevice

    safe = factory.SubFactory(SafeContractFactory)
    cloud_messaging_token = factory.faker('isbn13')
    build_number = factory.Sequence()
    bundle = 'company.package.app'
    device_type = 0
    version = '1.0.0'

