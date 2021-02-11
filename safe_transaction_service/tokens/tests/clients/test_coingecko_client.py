from django.test import TestCase

from eth_utils import is_checksum_address

from gnosis.eth import EthereumClient

from safe_transaction_service.history.tests.utils import \
    just_test_if_mainnet_node

from ...clients.coingecko_client import CoingeckoClient
from ...clients.kleros_client import KlerosClient


class TestCoingeckoClient(TestCase):
    def test_coingecko_client(self):
        coingecko_client = CoingeckoClient()

        non_existing_token_address = '0xda2f8b8386302C354a90DB670E40beA3563AF454'
        gno_token_address = '0x6810e776880C02933D47DB1b9fc05908e5386b96'

        self.assertGreater(coingecko_client.get_token_price(gno_token_address), 0)
        self.assertEqual(coingecko_client.get_token_price(non_existing_token_address), 0.)

        self.assertGreater(coingecko_client.get_price('energy-web-token'), 0)
