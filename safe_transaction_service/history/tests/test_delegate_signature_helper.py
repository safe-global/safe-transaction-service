from django.test import TestCase

from eth_account import Account
from eth_account.messages import defunct_hash_message

from ..helpers import DelegateSignatureDeprecatedHelper


class TestDelegateSignatureHelper(TestCase):
    def test_delegate_signature_helper(self):
        address = Account.create().address

        elements = {
            DelegateSignatureDeprecatedHelper.calculate_hash(address),
            DelegateSignatureDeprecatedHelper.calculate_hash(address, eth_sign=True),
            DelegateSignatureDeprecatedHelper.calculate_hash(
                address, previous_totp=True
            ),
            DelegateSignatureDeprecatedHelper.calculate_hash(
                address, eth_sign=True, previous_totp=True
            ),
        }
        self.assertEqual(len(elements), 4)  # Not repeated elements

    def test_delegate_eth_sign(self):
        totp = DelegateSignatureDeprecatedHelper.calculate_totp()
        address = Account.create().address
        message = address + str(totp)
        Account.sign_message
        signable_hash = defunct_hash_message(text=message)

        self.assertEqual(
            signable_hash,
            DelegateSignatureDeprecatedHelper.calculate_hash(address, eth_sign=True),
        )
