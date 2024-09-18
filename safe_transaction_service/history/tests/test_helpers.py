from unittest.mock import MagicMock

from django.test import TestCase

from hexbytes import HexBytes
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.history.helpers import DelegateSignatureHelperV2


class TestDelegateSignatureHelperV2(SafeTestCaseMixin, TestCase):

    def test_calculate_hash(self):
        # Mock calculate_totp
        DelegateSignatureHelperV2.calculate_totp = MagicMock(
            side_effect=lambda previous: 123456 if not previous else 654321
        )

        delegate_address = "0x1234567890123456789012345678901234567890"
        chain_id = 1

        # Hash calculated when totp previous is false
        expected_hash_previous_totp_false = HexBytes(
            "0x40ef28feb993bf127265260d48ab1a427d5b852aa8b38f511fcd368bfc9cbfdf"
        )

        result_hash = DelegateSignatureHelperV2.calculate_hash(
            delegate_address, chain_id, False
        )

        DelegateSignatureHelperV2.calculate_totp.assert_called_once_with(previous=False)
        self.assertEqual(result_hash, expected_hash_previous_totp_false)

        # Hash calculated when totp previous is true
        expected_hash_previous_totp_true = HexBytes(
            "0x37fe1c77d467e92109ef91637e30a4053bab963de2ea74f9d6c4ba1918ff32e6"
        )

        result_hash = DelegateSignatureHelperV2.calculate_hash(
            delegate_address, chain_id, True
        )

        DelegateSignatureHelperV2.calculate_totp.assert_called_with(previous=True)
        self.assertEqual(result_hash, expected_hash_previous_totp_true)
