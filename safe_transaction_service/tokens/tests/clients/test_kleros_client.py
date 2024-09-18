from django.test import TestCase

from safe_eth.eth import EthereumClient
from safe_eth.eth.utils import fast_is_checksum_address

from safe_transaction_service.history.tests.utils import just_test_if_mainnet_node

from ...clients.kleros_client import KlerosClient


class TestKlerosClient(TestCase):
    def test_kleros_client(self):
        mainnet_node = just_test_if_mainnet_node()
        kleros_client = KlerosClient(EthereumClient(mainnet_node))

        token_ids = kleros_client.get_token_ids()
        self.assertGreater(len(token_ids), 100)

        kleros_tokens = kleros_client.get_token_info(token_ids[:5])
        self.assertEqual(len(kleros_tokens), 5)
        for kleros_token in kleros_tokens:
            self.assertTrue(fast_is_checksum_address(kleros_token.address))
            self.assertTrue(kleros_token.symbol_multihash.startswith("/ipfs/"))
