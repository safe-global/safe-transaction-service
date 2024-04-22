from django.test import TestCase

from eth_account import Account
from eth_account.messages import defunct_hash_message

from ..helpers import DelegateSignatureHelper


class TestDelegateSignatureHelper(TestCase):
    def test_delegate_signature_helper(self):
        address = Account.create().address

        elements = {
            DelegateSignatureHelper.calculate_hash(address),
            DelegateSignatureHelper.calculate_hash(address, eth_sign=True),
            DelegateSignatureHelper.calculate_hash(address, previous_totp=True),
            DelegateSignatureHelper.calculate_hash(
                address, eth_sign=True, previous_totp=True
            ),
        }
        self.assertEqual(len(elements), 4)  # Not repeated elements

    def test_delegate_eth_sign(self):
        totp = DelegateSignatureHelper.calculate_totp()
        address = Account.create().address
        message = address + str(totp)
        Account.sign_message
        signable_hash = defunct_hash_message(text=message)

        self.assertEqual(
            signable_hash,
            DelegateSignatureHelper.calculate_hash(address, eth_sign=True),
        )
