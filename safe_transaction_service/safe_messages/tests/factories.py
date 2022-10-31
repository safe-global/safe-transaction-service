import factory
from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from factory.django import DjangoModelFactory

from ..models import SafeMessage, SafeMessageConfirmation


class SafeMessageFactory(DjangoModelFactory):
    class Meta:
        model = SafeMessage

    safe = factory.LazyFunction(lambda: Account.create().address)
    message_hash = factory.LazyAttribute(
        lambda o: defunct_hash_message(text=o.message).hex()
    )
    message = factory.Sequence(lambda n: f"message-{n}")
    proposed_by = factory.LazyFunction(lambda: Account.create().address)
    description = factory.Faker("sentence", nb_words=5)


class SafeMessageConfirmationFactory(DjangoModelFactory):
    class Meta:
        model = SafeMessageConfirmation

    class Params:
        signing_owner = Account.create()

    safe_message = factory.SubFactory(SafeMessageFactory)
    owner = factory.LazyAttribute(lambda o: o.signing_owner.address)
    signature = factory.LazyAttribute(
        lambda o: o.signing_owner.sign_message(
            encode_defunct(text=o.safe_message.message)
        )["signature"].hex()
    )
    signature_type = 3
