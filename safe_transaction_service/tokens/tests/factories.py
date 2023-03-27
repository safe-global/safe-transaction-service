import factory
from eth_account import Account
from factory.django import DjangoModelFactory

from .. import models


class TokenFactory(DjangoModelFactory):
    class Meta:
        model = models.Token

    address = factory.LazyFunction(lambda: Account.create().address)
    name = factory.Faker("cryptocurrency_name")
    symbol = factory.Faker("cryptocurrency_code")
    decimals = 18
    logo = factory.django.ImageField(color="yellow")
    trusted = False
    spam = False
    copy_price = None


class TokenListFactory(DjangoModelFactory):
    class Meta:
        model = models.TokenList

    url = factory.Faker("url")
