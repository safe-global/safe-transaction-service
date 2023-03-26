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
        ens_client = EnsClient(EthereumNetwork.GOERLI.value)  # Mainnet
        if not ens_client.is_available():
            self.skipTest("ENS Goerli Client is not available")

        self.assertEqual(
            ens_client.query_by_account("0x0D28d3C544757B9DBb99AC33FcB774534D7C8a7D"),
            {
                "registrations": [
                    {
                        "expiryDate": "2308985592",
                        "domain": {
                            "labelName": "safe-tx-service",
                            "labelhash": "0x4d9600e939c494d5af0e62d974199a3674381907b1a7469ff900d13ff74f04d1",
                            "name": "safe-tx-service.eth",
                            "isMigrated": True,
                            "parent": {"name": "eth"},
                        },
                    }
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
            EthereumNetwork.GOERLI,
            EthereumNetwork.MAINNET,
        ):
            with self.subTest(ethereum_network=ethereum_network):
                ens_client = EnsClient(ethereum_network)
                self.assertTrue(ens_client.is_available())
                with mock.patch.object(Session, "get", side_effect=IOError()):
                    self.assertFalse(ens_client.is_available())
