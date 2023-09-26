from unittest import mock
from unittest.mock import PropertyMock

from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..utils import get_safe_message_hash_for_message
from .factories import SafeMessageConfirmationFactory, SafeMessageFactory
from .mocks import get_eip712_payload_mock


class TestSafeMessage(SafeTestCaseMixin, TestCase):
    def test_str(self):
        # fast_keccak(encode_abi([DOMAIN_TYPEHASH_V1_3_0, ganache_chain_id, address])
        mock_domain_separator = b"k(\x81\xf6l\xa4\xbbS-cS\xf5u\xb7\xc1F\xf7\xf5l\xfaC\xce\xd1\x06\xb1j\xe2O\x16a.\x03"
        # Use same safe_address so hash is always the same
        safe_address = "0x20a3C95188E1c053800e54575A508baCe65761A7"
        for input, expected in [
            (
                "TestMessage",
                "Safe Message 0xb04a24aa07a51d1d8c3913e9493b3b1f88ed6a8a75430a9a8eda3ed3ce1897bc - TestMessage",
            ),
            (
                "TestMessageVeryLong",
                "Safe Message 0xe3db816540ce371e2703b8ec59bdd6fec32e0c6078f2e204a205fd6d81564f28 - TestMessageVery...",
            ),
            (
                get_eip712_payload_mock(),
                "Safe Message 0xbabb22f5c02a24db447b8f0136d6e26bb58cd6d068ebe8ab25c2221cfdf53e18 - {'types': {'EIP...",
            ),
        ]:
            with self.subTest(input=input):
                with mock.patch(
                    "gnosis.safe.safe.Safe.domain_separator",
                    return_value=mock_domain_separator,
                    new_callable=PropertyMock,
                ):
                    safe_message = SafeMessageFactory(safe=safe_address, message=input)
                    self.assertEqual(str(safe_message), expected)

    def test_factory(self):
        # 0x63EB7d344c819caAC85bAa1C28cC4C2c08776495
        owner_1_account = Account.from_key(
            "0x4923c57f121449492c2be3c8355904b5286b2486be9d1ff0241e29650c5f589d"
        )
        # 0x3456cbF38287EE5CAa40492e4Abf6319496c2B84
        owner_2_account = Account.from_key(
            "0xfe4a966a3bc93ccad16e2eacb867ba14f06cdf9a9957e6f0fdef1619494471df"
        )
        safe_message_1 = SafeMessageFactory(safe=self.deploy_test_safe().address)
        safe_message_confirmation_1 = SafeMessageConfirmationFactory(
            signing_owner=owner_1_account, safe_message=safe_message_1
        )
        safe_message = safe_message_confirmation_1.safe_message
        message = safe_message.message
        message_hash = safe_message.message_hash
        self.assertEqual(
            message_hash,
            get_safe_message_hash_for_message(safe_message.safe, message).hex(),
        )
        recovered_owner = Account._recover_hash(
            safe_message.message_hash,
            signature=safe_message_confirmation_1.signature,
        )
        self.assertEqual(
            safe_message_confirmation_1.owner,
            recovered_owner,
            "0x63EB7d344c819caAC85bAa1C28cC4C2c08776495",
        )
        self.assertEqual(
            safe_message.build_signature(),
            HexBytes(safe_message_confirmation_1.signature),
        )

        # Check building of signatures sorted
        safe_message_confirmation_2 = SafeMessageConfirmationFactory(
            signing_owner=owner_2_account, safe_message=safe_message
        )
        recovered_owner = Account._recover_hash(
            safe_message.message_hash,
            signature=safe_message_confirmation_2.signature,
        )
        self.assertEqual(
            safe_message_confirmation_2.owner,
            recovered_owner,
            "0x3456cbF38287EE5CAa40492e4Abf6319496c2B84",
        )
        # Signatures must be sorted as owner_2 < owner1
        expected_signature = HexBytes(safe_message_confirmation_2.signature) + HexBytes(
            safe_message_confirmation_1.signature
        )
        self.assertEqual(safe_message.build_signature(), expected_signature)
