from django.test import TestCase

from eth_utils import keccak

from gnosis.eth.ethereum_client import EthereumNetwork

from ...clients import EnsClient


class TestEnsClient(TestCase):
    def test_domain_hash_to_hex_str(self):
        domain_hash_bytes = keccak(text='gnosis')
        domain_hash_int = int.from_bytes(domain_hash_bytes, byteorder='big')

        result = EnsClient.domain_hash_to_hex_str(domain_hash_bytes)
        self.assertEqual(result, EnsClient.domain_hash_to_hex_str(domain_hash_int))
        self.assertEqual(len(result), 66)

        self.assertEqual(len(EnsClient.domain_hash_to_hex_str(b'')), 66)
        self.assertEqual(len(EnsClient.domain_hash_to_hex_str(None)), 66)
        self.assertEqual(len(EnsClient.domain_hash_to_hex_str(2)), 66)

    def test_query_by_domain_hash(self):
        ens_client = EnsClient(EthereumNetwork.MAINNET.value)  # Mainnet
        if not ens_client.is_available():
            self.skipTest('ENS Client is not available')

        # Query for gnosis domain
        domain_hash = keccak(text='gnosis')
        self.assertEqual('gnosis', ens_client.query_by_domain_hash(domain_hash))

        domain_hash_2 = keccak(text='notverycommon-domain-name-made-up-by-me-with-forbidden-word-ñ')
        self.assertIsNone(ens_client.query_by_domain_hash(domain_hash_2))
