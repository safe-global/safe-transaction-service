import factory
from eth_account import Account
from factory.django import DjangoModelFactory
from safe_eth.safe.safe_signature import SafeSignatureType
from safe_eth.util.util import to_0x_hex_str

from ..models import SafeMessage, SafeMessageConfirmation
from ..utils import get_hash_for_message, get_safe_message_hash_for_message


class SafeMessageFactory(DjangoModelFactory):
    class Meta:
        model = SafeMessage

    safe = factory.LazyFunction(lambda: Account.create().address)
    message = factory.Sequence(lambda n: f"message-{n}")
    proposed_by = factory.LazyFunction(lambda: Account.create().address)
    safe_app_id = factory.Sequence(lambda n: n)
    origin = factory.Sequence(lambda n: {"url": f"random-url-{n}"})

    @factory.lazy_attribute
    def message_hash(self) -> str:
        return to_0x_hex_str(
            get_safe_message_hash_for_message(
                self.safe, get_hash_for_message(self.message)
            )
        )


class SafeMessageConfirmationFactory(DjangoModelFactory):
    class Meta:
        model = SafeMessageConfirmation

    class Params:
        signing_owner = Account.create()

    safe_message = factory.SubFactory(SafeMessageFactory)
    owner = factory.LazyAttribute(lambda o: o.signing_owner.address)
    signature = factory.LazyAttribute(
        lambda o: o.signing_owner.unsafe_sign_hash(o.safe_message.message_hash)[
            "signature"
        ]
    )
    signature_type = SafeSignatureType.EOA.value
