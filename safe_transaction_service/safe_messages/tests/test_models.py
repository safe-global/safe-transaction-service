# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock
from unittest.mock import PropertyMock

from django.test import TestCase

import eth_abi
from eth_account import Account
from hexbytes import HexBytes
from safe_eth.eth.utils import fast_keccak
from safe_eth.safe.safe_signature import (
    SafeSignature,
    SafeSignatureContract,
    SafeSignatureType,
)
from safe_eth.safe.signatures import signature_to_bytes
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from ..models import SafeMessageConfirmation
from ..utils import get_message_encoded, get_safe_message_hash_and_preimage_for_message
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
                    "safe_eth.safe.safe.Safe.domain_separator",
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
            to_0x_hex_str(
                get_safe_message_hash_and_preimage_for_message(
                    safe_message.safe, fast_keccak(get_message_encoded(message))
                )[0]
            ),
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

    def test_build_eip1271_signature_empty(self):
        safe_message = SafeMessageFactory(safe=self.deploy_test_safe().address)
        self.assertEqual(safe_message.build_eip1271_signature(), b"")

    def test_build_eip1271_signature_eoa_only(self):
        owner_1 = Account.create()
        owner_2 = Account.create()
        safe = self.deploy_test_safe(
            owners=[owner_1.address, owner_2.address], threshold=2
        )
        safe_message = SafeMessageFactory(safe=safe.address)
        SafeMessageConfirmationFactory(signing_owner=owner_1, safe_message=safe_message)
        SafeMessageConfirmationFactory(signing_owner=owner_2, safe_message=safe_message)

        wrapped = safe_message.build_eip1271_signature()
        message_hash = HexBytes(safe_message.message_hash)

        # The wrapped blob must parse as a single SafeSignature whose owner is the Safe
        outer_signatures = SafeSignature.parse_signature(wrapped, message_hash)
        self.assertEqual(len(outer_signatures), 1)
        self.assertIsInstance(outer_signatures[0], SafeSignatureContract)
        self.assertEqual(outer_signatures[0].owner, safe.address)

        # Unwrapping the contract signature payload yields the two EOA sigs ordered ascending
        inner_signatures = SafeSignature.parse_signature(
            outer_signatures[0].contract_signature, message_hash
        )
        self.assertEqual(len(inner_signatures), 2)
        self.assertEqual(
            [sig.signature_type for sig in inner_signatures],
            [SafeSignatureType.EOA, SafeSignatureType.EOA],
        )
        recovered_owners = [sig.owner for sig in inner_signatures]
        self.assertEqual(recovered_owners, sorted(recovered_owners, key=str.lower))
        self.assertEqual(set(recovered_owners), {owner_1.address, owner_2.address})

    def test_build_eip1271_signature_with_contract_signature(self):
        """
        Cover the case the naive `build_signature` cannot: a confirmation whose owner is
        itself a Safe (nested EIP-1271). The wrapped blob must keep GS021 happy — every
        inner `CONTRACT_SIGNATURE` static must point to an offset ``>= n_signatures * 65``.
        """
        eoa_owner_1 = Account.create()
        eoa_owner_2 = Account.create()
        nested_eoa = Account.create()
        safe_owner = self.deploy_test_safe(owners=[nested_eoa.address])
        safe = self.deploy_test_safe(
            owners=[eoa_owner_1.address, eoa_owner_2.address, safe_owner.address],
            threshold=3,
        )
        safe_message = SafeMessageFactory(safe=safe.address)
        message_hash = HexBytes(safe_message.message_hash)

        # Two EOA confirmations via the factory
        SafeMessageConfirmationFactory(
            signing_owner=eoa_owner_1, safe_message=safe_message
        )
        SafeMessageConfirmationFactory(
            signing_owner=eoa_owner_2, safe_message=safe_message
        )

        # The Safe-owner confirmation: a CONTRACT_SIGNATURE whose payload is the nested EOA
        # signing the double-wrapped SafeMessage hash. The bytes here are synthetic: this
        # test verifies structural wrapping, not on-chain EIP-1271 validation.
        safe_owner_message_hash, _ = safe_owner.get_message_hash_and_preimage(
            message_hash
        )
        nested_eoa_sig = nested_eoa.unsafe_sign_hash(safe_owner_message_hash)[
            "signature"
        ]
        contract_signature_bytes = (
            signature_to_bytes(
                0,
                int.from_bytes(HexBytes(safe_owner.address), byteorder="big"),
                65,
            )
            + eth_abi.encode(["bytes"], [bytes(nested_eoa_sig)])[32:]
        )
        SafeMessageConfirmation.objects.create(
            safe_message=safe_message,
            owner=safe_owner.address,
            signature=contract_signature_bytes,
            signature_type=SafeSignatureType.CONTRACT_SIGNATURE.value,
        )

        wrapped = safe_message.build_eip1271_signature()

        # Outer wrap: single CONTRACT_SIGNATURE pointing to the Safe
        outer_signatures = SafeSignature.parse_signature(wrapped, message_hash)
        self.assertEqual(len(outer_signatures), 1)
        self.assertIsInstance(outer_signatures[0], SafeSignatureContract)
        self.assertEqual(outer_signatures[0].owner, safe.address)

        # Inner blob: three signatures, sorted ascending by owner.lower(), with the contract
        # sig's offset satisfying GS021 (>= 3 * 65 = 195).
        inner_signatures = SafeSignature.parse_signature(
            outer_signatures[0].contract_signature, message_hash
        )
        self.assertEqual(len(inner_signatures), 3)
        recovered_owners = [sig.owner for sig in inner_signatures]
        self.assertEqual(recovered_owners, sorted(recovered_owners, key=str.lower))
        self.assertEqual(
            set(recovered_owners),
            {eoa_owner_1.address, eoa_owner_2.address, safe_owner.address},
        )
        contract_sig_in_inner = next(
            sig
            for sig in inner_signatures
            if sig.signature_type == SafeSignatureType.CONTRACT_SIGNATURE
        )
        self.assertGreaterEqual(contract_sig_in_inner.s, 3 * 65)
        self.assertEqual(
            bytes(contract_sig_in_inner.contract_signature), bytes(nested_eoa_sig)
        )
