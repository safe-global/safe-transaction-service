from django.test import TestCase

from eth_account import Account
from safe_eth.eth import EthereumClient

from safe_transaction_service.history.tests.utils import just_test_if_mainnet_node

from ...clients.zerion_client import (
    UniswapComponent,
    ZerionPoolMetadata,
    ZerionUniswapV2TokenAdapterClient,
)


class TestZerionClient(TestCase):
    def test_zerion_client(self):
        mainnet_node = just_test_if_mainnet_node()
        client = ZerionUniswapV2TokenAdapterClient(EthereumClient(mainnet_node))
        owl_pool_address = "0xBA6329EAe69707D6A0F273Bd082f4a0807A6B011"

        expected = [
            UniswapComponent(
                address="0x1A5F9352Af8aF974bFC03399e3767DF6370d82e4",
                tokenType="ERC20",
                rate=0,
            ),
            UniswapComponent(
                address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                tokenType="ERC20",
                rate=0,
            ),
        ]
        components = client.get_components(owl_pool_address)
        for component in components:
            self.assertGreaterEqual(component.rate, 0)
            component.rate = 0

        self.assertEqual(components, expected)

        metadata = client.get_metadata(owl_pool_address)
        expected = ZerionPoolMetadata(
            address="0xBA6329EAe69707D6A0F273Bd082f4a0807A6B011",
            name="OWL/USDC Pool",
            symbol="UNI-V2",
            decimals=18,
        )
        self.assertEqual(metadata, expected)

        random_address = Account.create().address
        self.assertIsNone(client.get_components(random_address))
        self.assertIsNone(client.get_metadata(random_address))
