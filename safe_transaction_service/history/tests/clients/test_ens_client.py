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
        ens_client = EnsClient(EthereumNetwork.RINKEBY.value)  # Mainnet
        if not ens_client.is_available():
            self.skipTest("ENS Rinkeby Client is not available")

        self.assertEqual(
            ens_client.query_by_account("0x4323E6b155BCf0b25f8c4C0B37dA808e3550b521"),
            {
                "registrations": [
                    {
                        "expiryDate": "2257309961",
                        "domain": {
                            "labelName": "vivarox",
                            "labelhash": "0x3dad4bca5efcde980e9e7f3a9484749505648542b06c5f4f8b2dbdb767f67ba8",
                            "name": "vivarox.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "2257310351",
                        "domain": {
                            "labelName": "satoshinakamoto",
                            "labelhash": "0x595165e57d0d5a26f71f2f387c9e8208831fa957a18aad079218ce42a530bc6e",
                            "name": "satoshinakamoto.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    },
                    {
                        "expiryDate": "2320424525",
                        "domain": {
                            "labelName": "vitalik",
                            "labelhash": "0xaf2caa1c2ca1d027f1ac823b529d0a67cd144264b2789fa2ea4d63a67c7103cc",
                            "name": "vitalik.eth",
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
            EthereumNetwork.RINKEBY,
            EthereumNetwork.GOERLI,
            EthereumNetwork.MAINNET,
        ):
            with self.subTest(ethereum_network=ethereum_network):
                ens_client = EnsClient(ethereum_network)
                self.assertTrue(ens_client.is_available())
                with mock.patch.object(Session, "get", side_effect=IOError()):
                    self.assertFalse(ens_client.is_available())
