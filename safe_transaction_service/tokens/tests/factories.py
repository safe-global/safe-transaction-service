import factory

from gnosis.eth.utils import get_eth_address_with_key

from .. import models


class TokenFactory(factory.DjangoModelFactory):
    class Meta:
        model = models.Token

    address = factory.LazyFunction(lambda: get_eth_address_with_key()[0])
    name = factory.Faker('cryptocurrency_name')
    symbol = factory.Faker('cryptocurrency_code')
    description = factory.Faker('catch_phrase')
    decimals = 18
    logo_uri = ''
    website_uri = ''
    gas = True
    fixed_eth_conversion = 1
