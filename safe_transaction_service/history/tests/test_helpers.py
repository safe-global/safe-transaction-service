from unittest.mock import MagicMock

from django.test import TestCase

from hexbytes import HexBytes

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

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
            "0xc095ec37d1798b39b8cf9306a3d6788f6118f46a0d18fcfac037c8306bdbf397"
        )

        result_hash = DelegateSignatureHelperV2.calculate_hash(
            delegate_address, chain_id, False
        )

        DelegateSignatureHelperV2.calculate_totp.assert_called_once_with(previous=False)
        self.assertEqual(result_hash, expected_hash_previous_totp_false)

        # Hash calculated when totp previous is true
        expected_hash_previous_totp_true = HexBytes(
            "0xbf910dbf371090157231e49e7530c44b5ecf6a24fd4322be85465c13dbcb1459"
        )

        result_hash = DelegateSignatureHelperV2.calculate_hash(
            delegate_address, chain_id, True
        )

        DelegateSignatureHelperV2.calculate_totp.assert_called_with(previous=True)
        self.assertEqual(result_hash, expected_hash_previous_totp_true)
