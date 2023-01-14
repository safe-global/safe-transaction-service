from typing import List, Optional, Sequence, Tuple
from unittest import mock
from unittest.mock import MagicMock

from django.conf import settings
from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import (
    Erc721Info,
    Erc721Manager,
    EthereumClientProvider,
    InvalidERC721Info,
)
from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from safe_transaction_service.tokens.constants import ENS_CONTRACTS_WITH_TLD
from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.tests.factories import TokenFactory
from safe_transaction_service.utils.redis import get_redis

from ..services import CollectiblesService
from ..services.collectibles_service import (
    Collectible,
    CollectiblesServiceProvider,
    CollectibleWithMetadata,
    Erc721InfoWithLogo,
    MetadataRetrievalException,
    ipfs_to_http,
)
from .factories import ERC721TransferFactory
from .utils import just_test_if_mainnet_node


class TestCollectiblesService(EthereumTestCaseMixin, TestCase):
    def test_ipfs_to_http(self):
        regular_url = "http://testing-url/path/?arguments"
        self.assertEqual(ipfs_to_http(regular_url), regular_url)
        ipfs_url = "ipfs://testing-url/path/?arguments"
        result = ipfs_to_http(ipfs_url)
        self.assertTrue(result.startswith("http"))
        self.assertIn("ipfs/testing-url/path/?arguments", result)

        ipfs_with_path_url = "ipfs://ipfs/testing-url/path/?arguments"
        result = ipfs_to_http(ipfs_with_path_url)
        self.assertTrue(result.startswith("http"))
        self.assertNotIn("ipfs/ipfs", result)
        self.assertIn("ipfs/testing-url/path/?arguments", result)

    def test_get_collectibles(self):
        mainnet_node = just_test_if_mainnet_node()
        try:
            ethereum_client = EthereumClient(mainnet_node)
            EthereumClientProvider.instance = ethereum_client
            collectibles_service = CollectiblesService(ethereum_client, get_redis())

            # Caches empty
            self.assertFalse(collectibles_service.cache_token_info)

            safe_address = "0xfF501B324DC6d78dC9F983f140B9211c3EdB4dc7"
            ens_address = "0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85"
            ens_logo_uri = "/media/tokens/logos/ENS.png"
            ens_token_id = 93288724337340885726942883352789513739931149355867373088241393067029827792979
            dappcon_2020_address = "0x202d2f33449Bf46d6d32Ae7644aDA130876461a4"
            dappcon_token_id = 13
            dappcon_logo_uri = Token(
                address=dappcon_2020_address, name="", symbol=""
            ).get_full_logo_uri()
            self.assertEqual(
                collectibles_service.get_collectibles(safe_address), ([], 0)
            )

            erc721_addresses = [
                (dappcon_2020_address, dappcon_token_id),
                (ens_address, ens_token_id),  # ENS
            ]

            for erc721_address, token_id in erc721_addresses:
                ERC721TransferFactory(
                    to=safe_address, address=erc721_address, token_id=token_id
                )

            expected = [
                Collectible(
                    token_name="Ethereum Name Service",
                    token_symbol="ENS",
                    logo_uri=ens_logo_uri,
                    address=ens_address,
                    id=ens_token_id,
                    uri=None,
                ),
                Collectible(
                    token_name="DappCon2020",
                    token_symbol="D20",
                    logo_uri=dappcon_logo_uri,
                    address=dappcon_2020_address,
                    id=dappcon_token_id,
                    uri="https://us-central1-thing-1d2be.cloudfunctions.net/getThing?thingId=Q1c8y3PwYomxjW25sW3l",
                ),
            ]
            collectibles, _ = collectibles_service.get_collectibles(safe_address)
            self.assertEqual(len(collectibles), len(expected))
            self.assertCountEqual(collectibles, expected)

            expected = [
                CollectibleWithMetadata(
                    token_name="Ethereum Name Service",
                    token_symbol="ENS",
                    logo_uri=ens_logo_uri,
                    address=ens_address,
                    id=93288724337340885726942883352789513739931149355867373088241393067029827792979,
                    uri=None,
                    metadata={
                        "name": "safe-multisig.eth",
                        "description": ".eth ENS Domain",
                        "image": settings.TOKENS_ENS_IMAGE_URL,
                    },
                ),
                CollectibleWithMetadata(
                    token_name="DappCon2020",
                    token_symbol="D20",
                    logo_uri=dappcon_logo_uri,
                    address=dappcon_2020_address,
                    id=13,
                    uri="https://us-central1-thing-1d2be.cloudfunctions.net/getThing?thingId=Q1c8y3PwYomxjW25sW3l",
                    metadata={
                        "minted": "Minted on Mintbase.io",
                        "image": "https://firebasestorage.googleapis.com/v0/b/thing-1d2be.appspot.com/o/token%2Fasset-1581932081565?alt=media&token=57b47904-1782-40e0-ab6d-4f8ca82e6884",
                        "name": "Earlybird Ticket",
                        "forSale": False,
                        "minter": "",
                        "external_url": "https://mintbase.io/my-market/0x202d2f33449bf46d6d32ae7644ada130876461a4",
                        "fiatPrice": "$278.66",
                        "tags": [],
                        "mintedOn": {"_seconds": 1581932237, "_nanoseconds": 580000000},
                        "amountToMint": 10,
                        "contractAddress": "0x202d2f33449bf46d6d32ae7644ada130876461a4",
                        "type": "ERC721",
                        "attributes": [
                            {
                                "display_type": "date",
                                "value": 1599516000,
                                "trait_type": "Start Date",
                            },
                            {
                                "display_type": "date",
                                "value": 1599688800,
                                "trait_type": "End Date",
                            },
                            {
                                "value": "Holzmarktstraße 33, 10243 Berlin, Germany",
                                "trait_type": "location",
                            },
                            {
                                "value": "ChIJhz8mADlOqEcR2lw7-iNCoDM",
                                "trait_type": "place_id",
                            },
                            {"value": "https://dappcon.io/", "trait_type": "website"},
                        ],
                        "price": "1.1",
                        "description": "This NFT ticket gives you full access to the 3-day conference. \nDate: 8 - 10 September *** Location: Holzmarktstraße 33 I 10243 Berlin",
                        "numAvailable": 0,
                    },
                ),
            ]
            collectibles_with_metadata = (
                collectibles_service.get_collectibles_with_metadata(safe_address)
            )
            self.assertCountEqual(collectibles_with_metadata, expected)

            # Set ens trusted
            Token.objects.filter(address=ens_address).update(trusted=True)
            collectibles_with_metadata = (
                collectibles_service.get_collectibles_with_metadata(
                    safe_address, only_trusted=True
                )
            )
            self.assertCountEqual(collectibles_with_metadata, expected[:1])

            # Set ens spam
            Token.objects.filter(address=ens_address).update(trusted=False, spam=True)
            collectibles_with_metadata = (
                collectibles_service.get_collectibles_with_metadata(
                    safe_address, exclude_spam=True
                )
            )
            self.assertCountEqual(collectibles_with_metadata, expected[1:])

            # Caches not empty
            self.assertTrue(collectibles_service.cache_token_info)
        finally:
            del EthereumClientProvider.instance

    @mock.patch.object(CollectiblesService, "get_metadata", autospec=True)
    @mock.patch.object(CollectiblesService, "get_collectibles", autospec=True)
    def test_get_collectibles_with_metadata(
        self, get_collectibles_mock: MagicMock, get_metadata_mock: MagicMock
    ):
        collectibles_service = CollectiblesServiceProvider()
        get_metadata_mock.return_value = "not-a-dictionary"
        collectible = Collectible(
            "GoldenSun",
            "Djinn",
            "http://random-address.org/logo.png",
            Account.create().address,
            28,
            "http://random-address.org/info-28.json",
        )
        get_collectibles_mock.return_value = [collectible], 0
        safe_address = Account.create().address

        expected = [
            CollectibleWithMetadata(
                collectible.token_name,
                collectible.token_symbol,
                collectible.logo_uri,
                collectible.address,
                collectible.id,
                collectible.uri,
                {},
            )
        ]
        self.assertListEqual(
            collectibles_service.get_collectibles_with_metadata(safe_address),
            expected,
        )
        get_metadata_mock.return_value = {}
        self.assertListEqual(
            collectibles_service.get_collectibles_with_metadata(safe_address),
            expected,
        )

        get_metadata_mock.side_effect = MetadataRetrievalException
        self.assertListEqual(
            collectibles_service.get_collectibles_with_metadata(safe_address),
            expected,
        )
        get_metadata_mock.side_effect = None

        metadata = {
            "name": "Gust",
            "description": "Jupiter Djinni",
            "image": "http://random-address.org/logo-28.png",
        }
        get_metadata_mock.return_value = metadata
        # collectible cached by address + id
        collectible.id += 1
        get_collectibles_mock.return_value = [collectible], 0
        collectible_with_metadata = CollectibleWithMetadata(
            collectible.token_name,
            collectible.token_symbol,
            collectible.logo_uri,
            collectible.address,
            collectible.id,
            collectible.uri,
            metadata,
        )
        self.assertEqual(collectible_with_metadata.name, "Gust")
        self.assertEqual(collectible_with_metadata.description, "Jupiter Djinni")
        self.assertEqual(
            collectible_with_metadata.image_uri, "http://random-address.org/logo-28.png"
        )
        expected = [collectible_with_metadata]

        self.assertListEqual(
            collectibles_service.get_collectibles_with_metadata(safe_address),
            expected,
        )

    @mock.patch.object(Erc721Manager, "get_info", autospec=True)
    def test_get_token_info(self, get_info_mock: MagicMock):
        collectibles_service = CollectiblesServiceProvider()
        random_address = Account.create().address

        # No DB, no blockchain source
        get_info_mock.side_effect = InvalidERC721Info
        self.assertFalse(collectibles_service.cache_token_info)
        self.assertIsNone(collectibles_service.get_token_info(random_address))
        self.assertTrue(
            collectibles_service.cache_token_info
        )  # Cache works for not found tokens too

        # Add DB source
        token = TokenFactory()
        self.assertEqual(
            collectibles_service.get_token_info(token.address),
            Erc721InfoWithLogo.from_token(token),
        )

        # Just Blockchain source
        random_address = Account.create().address
        self.assertEqual(Token.objects.count(), 1)
        get_info_mock.side_effect = None
        get_info_mock.return_value = Erc721Info("Uxio Collectible Card", "UCC")
        token_info = collectibles_service.get_token_info(random_address)
        self.assertIsInstance(token_info, Erc721InfoWithLogo)
        self.assertEqual(token_info.name, get_info_mock.return_value.name)
        self.assertEqual(token_info.symbol, get_info_mock.return_value.symbol)
        self.assertEqual(Token.objects.count(), 2)

        # Test switch name-symbol when symbol is way longer than name
        random_address = Account.create().address
        get_info_mock.return_value = Erc721Info(
            "POAP", "The Proof of Attendance Protocol"
        )
        token_info = collectibles_service.get_token_info(random_address)
        self.assertIsInstance(token_info, Erc721InfoWithLogo)
        self.assertEqual(token_info.symbol, get_info_mock.return_value.name)
        self.assertEqual(token_info.name, get_info_mock.return_value.symbol)
        self.assertEqual(Token.objects.count(), 3)
        self.assertEqual(
            len(collectibles_service.cache_token_info), 4
        )  # Cache works for not found tokens too

        # Test ENS (hardcoded)
        get_info_mock.return_value = None
        ens_token_address = list(ENS_CONTRACTS_WITH_TLD.keys())[0]
        token_info = collectibles_service.get_token_info(ens_token_address)
        self.assertIsNotNone(token_info)
        ens_logo_uri = "/media/tokens/logos/ENS.png"
        self.assertEqual(token_info.logo_uri, ens_logo_uri)
        self.assertEqual(Token.objects.count(), 4)
        self.assertEqual(
            Token.objects.get(address=ens_token_address).logo.url, ens_logo_uri
        )

    @mock.patch.object(Erc721Manager, "get_token_uris", autospec=True)
    def test_get_token_uris(self, get_token_uris_mock: MagicMock):
        redis = get_redis()
        redis.flushall()
        token_uris = [
            "http://testing.com/12",
            None,
            "",
        ]  # '' will be parsed as None by the service
        expected_token_uris = ["http://testing.com/12", None, None]
        get_token_uris_mock.return_value = token_uris
        addresses_with_token_ids = [(Account.create().address, i) for i in range(3)]
        collectibles_service = CollectiblesServiceProvider()
        self.assertEqual(
            collectibles_service.get_token_uris(addresses_with_token_ids),
            expected_token_uris,
        )

        # Test redis cache
        redis_keys = redis.keys("token-uri:*")
        self.assertEqual(len(redis_keys), 3)

        # Test redis cache working
        self.assertEqual(
            collectibles_service.get_token_uris(addresses_with_token_ids),
            expected_token_uris,
        )

    @mock.patch.object(Erc721Manager, "get_token_uris", autospec=True)
    def test_get_token_uris_value_error(self, get_token_uris_mock: MagicMock):
        """
        Test node error when retrieving the uris
        """

        def get_token_uris_fn(
            self, token_addresses_with_token_ids: Sequence[Tuple[str, int]]
        ) -> List[Optional[str]]:
            if (
                "0x9807559b75D5fcCEcf1bbe074FD0890EdDC1bf79",
                8,
            ) in token_addresses_with_token_ids:
                raise ValueError
            else:
                return [
                    f"https://random-url/{token_id}.json"
                    for _, token_id in token_addresses_with_token_ids
                ]

        # Random addresses
        addresses_with_token_ids = [
            ("0xaa2475C106A01eA6972dBC9d6b975cD122b06b80", 4),
            ("0x9807559b75D5fcCEcf1bbe074FD0890EdDC1bf79", 8),
            ("0xD7E7f8F69dbaEe520182386099364046d1e1B80c", 15),
        ]
        get_token_uris_mock.side_effect = get_token_uris_fn
        collectibles_service = CollectiblesServiceProvider()

        self.assertEqual(
            collectibles_service.get_token_uris(addresses_with_token_ids),
            [
                "https://random-url/4.json",
                None,
                "https://random-url/15.json",
            ],
        )

    def test_retrieve_metadata_from_uri(self):
        collectibles_service = CollectiblesServiceProvider()
        # Test ipfs
        ipfs_address = "ipfs://ipfs/Qmc4ZMDNMu5bguGohtGQGx5DQexitnNvf5Rb7Yzbja47bo"
        expected_object = {
            "description": "Flamingo DAO Initial Token",
            "name": "Flamingo DAO",
            "image": "https://ipfs.io/ipfs/QmXKU5RBTrGaYn5M1iWQaeKuCKV34g417YDGN5Yh7Uxk4i",
        }

        self.assertEqual(
            collectibles_service._retrieve_metadata_from_uri(ipfs_address),
            expected_object,
        )
