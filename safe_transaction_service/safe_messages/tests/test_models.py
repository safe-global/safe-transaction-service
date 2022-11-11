from django.test import TestCase

from eth_account import Account
from eth_account.messages import defunct_hash_message, encode_defunct
from hexbytes import HexBytes

from .factories import SafeMessageConfirmationFactory


class TestSafeMessage(TestCase):
    def test_factory(self):
        # 0x63EB7d344c819caAC85bAa1C28cC4C2c08776495
        owner_1_account = Account.from_key(
            "0x4923c57f121449492c2be3c8355904b5286b2486be9d1ff0241e29650c5f589d"
        )
        # 0x3456cbF38287EE5CAa40492e4Abf6319496c2B84
        owner_2_account = Account.from_key(
            "0xfe4a966a3bc93ccad16e2eacb867ba14f06cdf9a9957e6f0fdef1619494471df"
        )

        safe_message_confirmation_1 = SafeMessageConfirmationFactory(
            signing_owner=owner_1_account
        )
        safe_message = safe_message_confirmation_1.safe_message
        message = safe_message.message
        message_hash = safe_message.message_hash
        self.assertEqual(message_hash, defunct_hash_message(text=message).hex())
        recovered_owner = Account.recover_message(
            encode_defunct(text=message),
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
        recovered_owner = Account.recover_message(
            encode_defunct(text=message),
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
