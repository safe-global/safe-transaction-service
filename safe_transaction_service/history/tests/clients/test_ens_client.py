from unittest import mock

from django.test import TestCase

from eth_utils import keccak
from requests import Session

from gnosis.eth.ethereum_client import EthereumNetwork

from ...clients import EnsClient


class TestEnsClient(TestCase):
    def test_domain_hash_to_hex_str(self):
        domain_hash_bytes = keccak(text="gnosis")
        domain_hash_int = int.from_bytes(domain_hash_bytes, byteorder="big")

        result = EnsClient.domain_hash_to_hex_str(domain_hash_bytes)
        self.assertEqual(result, EnsClient.domain_hash_to_hex_str(domain_hash_int))
        self.assertEqual(len(result), 66)

        self.assertEqual(len(EnsClient.domain_hash_to_hex_str(b"")), 66)
        self.assertEqual(len(EnsClient.domain_hash_to_hex_str(None)), 66)
        self.assertEqual(len(EnsClient.domain_hash_to_hex_str(2)), 66)

    def test_query_by_account(self):
        ens_client = EnsClient(EthereumNetwork.MAINNET.value)
        if not ens_client.is_available():
            self.skipTest("ENS Mainnet Client is not available")

        self.assertEqual(
            ens_client.query_by_account("0x70608b1809c93Ec57160C266a38322144E9A9d28"),
            {
                "registrations": [
                    {
                        "expiryDate": "1763372829",
                        "domain": {
                            "labelName": "safe-treasury",
                            "labelhash": "0x136ff778d0f4bb244b1284dd5835c78a9fb425680d3a75aab24db723042494af",
                            "name": "safe-treasury.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1775002833",
                        "domain": {
                            "labelName": "gnosis-safe",
                            "labelhash": "0x162be7f136f104c8cc5ce333cdb2ef94fa8270f4ca186ba6083634b8b93efa82",
                            "name": "gnosis-safe.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1763371973",
                        "domain": {
                            "labelName": "safe-dao",
                            "labelhash": "0x3dcf430070cc5f52fbe66433a72fc6eed2860b28527f9016933599d41cbf6d9e",
                            "name": "safe-dao.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1763373078",
                        "domain": {
                            "labelName": "safe-foundation",
                            "labelhash": "0x50270c4c4cf9837870f71a836cc4ab37d29e0a452eda3caa1b39cc8a29b96e90",
                            "name": "safe-foundation.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1824427603",
                        "domain": {
                            "labelName": "safe",
                            "labelhash": "0xc318ae71df18dafd8fbd063284586ea242aa3d51bc2950f71d70d7fc205b875f",
                            "name": "safe.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1763372390",
                        "domain": {
                            "labelName": "safe-token",
                            "labelhash": "0xc9ccb8a54110c76c01d4f63e9a9d760d8fd803aba14f4d2fa408200cc6b68cba",
                            "name": "safe-token.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1763309068",
                        "domain": {
                            "labelName": "safe-multisig",
                            "labelhash": "0xce3f8bfd04bb347a13abbf6faca8dc5e4a281345a316019206742b60b6f1b053",
                            "name": "safe-multisig.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "1764337847",
                        "domain": {
                            "labelName": "takebackownership",
                            "labelhash": "0xedc916efb805eea66b4d5496f670c0166ccd9d2453ded805fe1d82738944e8df",
                            "name": "takebackownership.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                ]
            },
        )

    def test_query_by_domain_hash(self):
        ens_client = EnsClient(EthereumNetwork.MAINNET.value)  # Mainnet
        if not ens_client.is_available():
            self.skipTest("ENS Mainnet Client is not available")

        # Query for gnosis domain
        domain_hash = keccak(text="gnosis")
        self.assertEqual("gnosis", ens_client.query_by_domain_hash(domain_hash))

        domain_hash_2 = keccak(
            text="notverycommon-domain-name-made-up-by-me-with-forbidden-word-ñ"
        )
        self.assertIsNone(ens_client.query_by_domain_hash(domain_hash_2))

    def test_is_available(self):
        for ethereum_network in (
            EthereumNetwork.ROPSTEN,
            EthereumNetwork.MAINNET,
        ):
            with self.subTest(ethereum_network=ethereum_network):
                ens_client = EnsClient(ethereum_network)
                self.assertTrue(ens_client.is_available())
                with mock.patch.object(Session, "get", side_effect=IOError()):
                    self.assertFalse(ens_client.is_available())
