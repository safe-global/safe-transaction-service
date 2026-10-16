# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import TestCase

from eth_abi import encode as encode_abi
from eth_account import Account
from safe_eth.eth.constants import NULL_ADDRESS

from ..constants import COSIGNER_POLICY, ERC20_TRANSFER_POLICY
from ..decoders import (
    CoSignerPolicyDataDecoder,
    Erc20TransferPolicyDataDecoder,
    PolicyDataDecoderRegistry,
    policy_data_decoder_registry,
)
from .factories import PolicyContractFactory


class TestErc20TransferPolicyDataDecoder(TestCase):
    def setUp(self):
        self.decoder = Erc20TransferPolicyDataDecoder()

    def test_abi_types_derived_from_abi_inputs(self):
        self.assertEqual(self.decoder.abi_types, ["(address,bool)[]"])

    def test_decode(self):
        recipients = [Account.create().address for _ in range(2)]
        data = encode_abi(
            ["(address,bool)[]"], [[(recipients[0], True), (recipients[1], False)]]
        )

        self.assertEqual(
            self.decoder.decode(data),
            {
                "recipients": [
                    {"recipient": recipients[0], "allowed": True},
                    {"recipient": recipients[1], "allowed": False},
                ]
            },
        )

    def test_decode_checksums_addresses_inside_the_struct(self):
        recipient = Account.create().address
        data = encode_abi(["(address,bool)[]"], [[(recipient.lower(), True)]])

        decoded = self.decoder.decode(data)

        self.assertEqual(decoded["recipients"][0]["recipient"], recipient)

    def test_decode_empty_list(self):
        self.assertEqual(
            self.decoder.decode(encode_abi(["(address,bool)[]"], [[]])),
            {"recipients": []},
        )


class TestCoSignerPolicyDataDecoder(TestCase):
    def test_decode(self):
        cosigner = Account.create().address
        self.assertEqual(
            CoSignerPolicyDataDecoder().decode(encode_abi(["address"], [cosigner])),
            {"cosigner": cosigner},
        )


class TestPolicyDataDecoderRegistry(TestCase):
    def test_register_duplicated_name(self):
        registry = PolicyDataDecoderRegistry()
        registry.register(CoSignerPolicyDataDecoder())

        with self.assertRaisesMessage(
            ValueError, f"A decoder for {COSIGNER_POLICY} is already registered"
        ):
            registry.register(CoSignerPolicyDataDecoder())

    def test_decode(self):
        cosigner = Account.create().address
        policy_contract = PolicyContractFactory(name=COSIGNER_POLICY)

        self.assertEqual(
            policy_data_decoder_registry.decode(
                policy_contract.address, encode_abi(["address"], [cosigner])
            ),
            {"policy_name": COSIGNER_POLICY, "parameters": {"cosigner": cosigner}},
        )

    def test_decode_unknown_policy(self):
        data = encode_abi(["address"], [Account.create().address])

        # Not on the database
        self.assertIsNone(
            policy_data_decoder_registry.decode(Account.create().address, data)
        )
        # On the database, but without a decoder
        policy_contract = PolicyContractFactory(name="NotDecodedPolicy")
        self.assertIsNone(
            policy_data_decoder_registry.decode(policy_contract.address, data)
        )
        # A removed policy is never decodable
        self.assertIsNone(policy_data_decoder_registry.decode(NULL_ADDRESS, data))

    def test_decode_malformed_data(self):
        policy_contract = PolicyContractFactory(name=ERC20_TRANSFER_POLICY)

        for data in (b"", b"\x01\x02\x03", encode_abi(["address"], [NULL_ADDRESS])):
            with self.subTest(data=data):
                self.assertIsNone(
                    policy_data_decoder_registry.decode(policy_contract.address, data)
                )

    def test_decode_memoryview(self):
        """`BinaryField` returns a `memoryview` when the model is read from the database"""
        cosigner = Account.create().address
        policy_contract = PolicyContractFactory(name=COSIGNER_POLICY)

        decoded = policy_data_decoder_registry.decode(
            policy_contract.address, memoryview(encode_abi(["address"], [cosigner]))
        )
        self.assertEqual(decoded["parameters"], {"cosigner": cosigner})
