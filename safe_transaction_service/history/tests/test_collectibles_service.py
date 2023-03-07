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
from .mocks.mock_dappcon_nft import dappcon_nft_metadata_mock
from .utils import just_test_if_mainnet_node


class TestCollectiblesService(EthereumTestCaseMixin, TestCase):
    def setUp(self) -> None:
        get_redis().flushall()

    def tearDown(self) -> None:
        get_redis().flushall()

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

    @mock.patch(
        "safe_transaction_service.history.services.collectibles_service.CollectiblesService._retrieve_metadata_from_uri"
    )
    def test_get_collectibles(self, retrieve_metadata_from_uri_mock: MagicMock):
        retrieve_metadata_from_uri_mock.return_value = dappcon_nft_metadata_mock

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
                    metadata=dappcon_nft_metadata_mock,
                ),
            ]
            collectibles_with_metadata = (
                collectibles_service.get_collectibles_with_metadata_paginated(
                    safe_address
                )
            )
            self.assertCountEqual(collectibles_with_metadata[0], expected)
            self.assertEqual(collectibles_with_metadata[1], 2)

            # Set ens trusted to only retrieve trusted tokens
            Token.objects.filter(address=ens_address).update(trusted=True)
            collectibles_with_metadata = (
                collectibles_service.get_collectibles_with_metadata_paginated(
                    safe_address, only_trusted=True
                )
            )

            self.assertCountEqual(collectibles_with_metadata[0], expected[:1])
            self.assertEqual(collectibles_with_metadata[1], 1)

            # Set ens spam so it will be excluded
            Token.objects.filter(address=ens_address).update(trusted=False, spam=True)
            collectibles_with_metadata = (
                collectibles_service.get_collectibles_with_metadata_paginated(
                    safe_address, exclude_spam=True
                )
            )

            self.assertCountEqual(collectibles_with_metadata[0], expected[1:])
            self.assertEqual(collectibles_with_metadata[1], 1)

            # Caches not empty
            self.assertTrue(collectibles_service.cache_token_info)
        finally:
            del EthereumClientProvider.instance

    @mock.patch.object(CollectiblesService, "get_metadata", autospec=True)
    @mock.patch.object(CollectiblesService, "get_collectibles", autospec=True)
    def test_get_collectibles_with_metadata_paginated(
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
        get_collectibles_mock.return_value = [collectible], 1
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
        collectibles_with_metadata_paginated = (
            collectibles_service.get_collectibles_with_metadata_paginated(safe_address)
        )
        self.assertListEqual(
            collectibles_with_metadata_paginated[0],
            expected,
        )
        self.assertEqual(collectibles_with_metadata_paginated[1], 1)

        get_metadata_mock.return_value = {}
        self.assertListEqual(
            collectibles_service.get_collectibles_with_metadata_paginated(safe_address)[
                0
            ],
            expected,
        )

        get_metadata_mock.side_effect = MetadataRetrievalException
        self.assertListEqual(
            collectibles_service.get_collectibles_with_metadata_paginated(safe_address)[
                0
            ],
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
        get_collectibles_mock.return_value = [collectible], 5
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

        collectibles_with_metadata_paginated = (
            collectibles_service.get_collectibles_with_metadata_paginated(safe_address)
        )
        self.assertListEqual(
            collectibles_with_metadata_paginated[0],
            expected,
        )
        self.assertEqual(collectibles_with_metadata_paginated[1], 5)

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
        uri = "ipfs://ipfs/Qmc4ZMDNMu5bguGohtGQGx5DQexitnNvf5Rb7Yzbja47bo"
        expected_object = {
            "description": "Flamingo DAO Initial Token",
            "name": "Flamingo DAO",
            "image": "https://ipfs.io/ipfs/QmXKU5RBTrGaYn5M1iWQaeKuCKV34g417YDGN5Yh7Uxk4i",
        }

        self.assertEqual(
            collectibles_service._retrieve_metadata_from_uri(uri),
            expected_object,
        )

    def test_retrieve_metadata_from_uri_base_64(self):
        collectibles_service = CollectiblesServiceProvider()
        # Test b64 encoded uri
        uri = "data:application/json;base64,eyJ0b2tlbiI6IjE2ODYiLCAiaW1hZ2UiOiJkYXRhOmltYWdlL3N2Zyt4bWw7YmFzZTY0LFBITjJaeUI0Yld4dWN6MGlhSFIwY0RvdkwzZDNkeTUzTXk1dmNtY3ZNakF3TUM5emRtY2lJSGRwWkhSb1BTSXlNREFpSUdobGFXZG9kRDBpTWpBd0lpQjJhV1YzUW05NFBTSXdJREFnTWpBd0lESXdNQ0lnYzNSNWJHVTlJbUpoWTJ0bmNtOTFibVE2WkdWbGNITnJlV0pzZFdVaVBqeHdZWFJvSUdROUlrMDJPQzQwTkNBeE5ETXVORFJETmpFdU9EZ2dNVFF6TGpRMElEVTJMakEwSURFME1TNDROQ0ExTUM0NU1pQXhNemd1TmpSRE5EVXVPQ0F4TXpVdU16WWdOREV1TnpZZ01UTXdMalk0SURNNExqZ2dNVEkwTGpaRE16VXVPRFFnTVRFNExqVXlJRE0wTGpNMklERXhNUzR5SURNMExqTTJJREV3TWk0Mk5FTXpOQzR6TmlBNU5DNHhOaUF6TlM0NE5DQTROaTQ0T0NBek9DNDRJRGd3TGpoRE5ERXVPRFFnTnpRdU5qUWdORFV1T1RZZ05qa3VPVFlnTlRFdU1UWWdOall1TnpaRE5UWXVORFFnTmpNdU5EZ2dOakl1TkRnZ05qRXVPRFFnTmprdU1qZ2dOakV1T0RSRE56UXVORGdnTmpFdU9EUWdOemd1T0RRZ05qSXVPRGdnT0RJdU16WWdOalF1T1RaRE9EVXVPRGdnTmpZdU9UWWdPRGd1TnpZZ05qa3VNVElnT1RFZ056RXVORFJNT0RVdU16WWdOemN1T0VNNE15NDBOQ0EzTlM0M01pQTRNUzR5SURjMElEYzRMalkwSURjeUxqWTBRemMyTGpFMklEY3hMakk0SURjekxqQTBJRGN3TGpZZ05qa3VNamdnTnpBdU5rTTJOQzQwSURjd0xqWWdOakF1TVRJZ056RXVPVElnTlRZdU5EUWdOelF1TlRaRE5USXVOellnTnpjdU1USWdORGt1T0RnZ09EQXVOellnTkRjdU9DQTROUzQwT0VNME5TNDRJRGt3TGpJZ05EUXVPQ0E1TlM0NE5DQTBOQzQ0SURFd01pNDBRelEwTGpnZ01UQTVMakEwSURRMUxqYzJJREV4TkM0M05pQTBOeTQyT0NBeE1Ua3VOVFpETkRrdU5pQXhNalF1TXpZZ05USXVNellnTVRJNExqQTRJRFUxTGprMklERXpNQzQzTWtNMU9TNDFOaUF4TXpNdU16WWdOak11T1RJZ01UTTBMalk0SURZNUxqQTBJREV6TkM0Mk9FTTNNUzQzTmlBeE16UXVOamdnTnpRdU16WWdNVE0wTGpJNElEYzJMamcwSURFek15NDBPRU0zT1M0ek1pQXhNekl1TmlBNE1TNHlPQ0F4TXpFdU5EUWdPREl1TnpJZ01UTXdWakV3T1M0ME9FZzJOMVl4TURFdU1rZzVNUzQ1TmxZeE16UXVNekpET0RrdU5EZ2dNVE0yTGpnNElEZzJMaklnTVRNNUxqQTBJRGd5TGpFeUlERTBNQzQ0UXpjNExqRXlJREUwTWk0MU5pQTNNeTQxTmlBeE5ETXVORFFnTmpndU5EUWdNVFF6TGpRMFdrMHhNelV1T1RVeklERTBNeTQwTkVNeE16QXVPRE16SURFME15NDBOQ0F4TWpZdU1EY3pJREUwTWk0eU5DQXhNakV1TmpjeklERXpPUzQ0TkVNeE1UY3VNelV6SURFek55NDBOQ0F4TVRNdU9ETXpJREV6TXk0NU5pQXhNVEV1TVRFeklERXlPUzQwUXpFd09DNDBOek1nTVRJMExqZzBJREV3Tnk0eE5UTWdNVEU1TGpNMklERXdOeTR4TlRNZ01URXlMamsyUXpFd055NHhOVE1nTVRBMkxqUWdNVEE0TGpRM015QXhNREF1T0RRZ01URXhMakV4TXlBNU5pNHlPRU14TVRNdU9ETXpJRGt4TGpjeUlERXhOeTR6TlRNZ09EZ3VNalFnTVRJeExqWTNNeUE0TlM0NE5FTXhNall1TURjeklEZ3pMalEwSURFek1DNDRNek1nT0RJdU1qUWdNVE0xTGprMU15QTRNaTR5TkVNeE5ERXVNRGN6SURneUxqSTBJREUwTlM0M09UTWdPRE11TkRRZ01UVXdMakV4TXlBNE5TNDRORU14TlRRdU5URXpJRGc0TGpJMElERTFPQzR3TXpNZ09URXVOeklnTVRZd0xqWTNNeUE1Tmk0eU9FTXhOak11TXpreklERXdNQzQ0TkNBeE5qUXVOelV6SURFd05pNDBJREUyTkM0M05UTWdNVEV5TGprMlF6RTJOQzQzTlRNZ01URTVMak0ySURFMk15NHpPVE1nTVRJMExqZzBJREUyTUM0Mk56TWdNVEk1TGpSRE1UVTRMakF6TXlBeE16TXVPVFlnTVRVMExqVXhNeUF4TXpjdU5EUWdNVFV3TGpFeE15QXhNemt1T0RSRE1UUTFMamM1TXlBeE5ESXVNalFnTVRReExqQTNNeUF4TkRNdU5EUWdNVE0xTGprMU15QXhORE11TkRSYVRURXpOUzQ1TlRNZ01UTTFMakk0UXpFek9TNDNNVE1nTVRNMUxqSTRJREUwTWk0NU9UTWdNVE0wTGpNMklERTBOUzQzT1RNZ01UTXlMalV5UXpFME9DNDFPVE1nTVRNd0xqWWdNVFV3TGpjMU15QXhNamN1T1RZZ01UVXlMakkzTXlBeE1qUXVOa014TlRNdU56a3pJREV5TVM0eU5DQXhOVFF1TlRVeklERXhOeTR6TmlBeE5UUXVOVFV6SURFeE1pNDVOa014TlRRdU5UVXpJREV3T0M0ME9DQXhOVE11TnpreklERXdOQzQxTmlBeE5USXVNamN6SURFd01TNHlRekUxTUM0M05UTWdPVGN1TnpZZ01UUTRMalU1TXlBNU5TNHhNaUF4TkRVdU56a3pJRGt6TGpJNFF6RTBNaTQ1T1RNZ09URXVNellnTVRNNUxqY3hNeUE1TUM0MElERXpOUzQ1TlRNZ09UQXVORU14TXpJdU1Ua3pJRGt3TGpRZ01USTRMamt4TXlBNU1TNHpOaUF4TWpZdU1URXpJRGt6TGpJNFF6RXlNeTR6T1RNZ09UVXVNVElnTVRJeExqSXpNeUE1Tnk0M05pQXhNVGt1TmpNeklERXdNUzR5UXpFeE9DNHhNVE1nTVRBMExqVTJJREV4Tnk0ek5UTWdNVEE0TGpRNElERXhOeTR6TlRNZ01URXlMamsyUXpFeE55NHpOVE1nTVRFM0xqTTJJREV4T0M0eE1UTWdNVEl4TGpJMElERXhPUzQyTXpNZ01USTBMalpETVRJeExqSXpNeUF4TWpjdU9UWWdNVEl6TGpNNU15QXhNekF1TmlBeE1qWXVNVEV6SURFek1pNDFNa014TWpndU9URXpJREV6TkM0ek5pQXhNekl1TVRreklERXpOUzR5T0NBeE16VXVPVFV6SURFek5TNHlPRnBOTVRJMExqTXhNeUEzTVM0ME5FTXhNakl1TXpreklEY3hMalEwSURFeU1DNDNPVE1nTnpBdU9DQXhNVGt1TlRFeklEWTVMalV5UXpFeE9DNHpNVE1nTmpndU1UWWdNVEUzTGpjeE15QTJOaTQxTmlBeE1UY3VOekV6SURZMExqY3lRekV4Tnk0M01UTWdOakl1T0RnZ01URTRMak14TXlBMk1TNHpNaUF4TVRrdU5URXpJRFl3TGpBMFF6RXlNQzQzT1RNZ05UZ3VOamdnTVRJeUxqTTVNeUExT0NBeE1qUXVNekV6SURVNFF6RXlOaTR5TXpNZ05UZ2dNVEkzTGpjNU15QTFPQzQyT0NBeE1qZ3VPVGt6SURZd0xqQTBRekV6TUM0eU56TWdOakV1TXpJZ01UTXdMamt4TXlBMk1pNDRPQ0F4TXpBdU9URXpJRFkwTGpjeVF6RXpNQzQ1TVRNZ05qWXVOVFlnTVRNd0xqSTNNeUEyT0M0eE5pQXhNamd1T1RreklEWTVMalV5UXpFeU55NDNPVE1nTnpBdU9DQXhNall1TWpNeklEY3hMalEwSURFeU5DNHpNVE1nTnpFdU5EUmFUVEUwTnk0MU9UTWdOekV1TkRSRE1UUTFMalkzTXlBM01TNDBOQ0F4TkRRdU1EY3pJRGN3TGpnZ01UUXlMamM1TXlBMk9TNDFNa014TkRFdU5Ua3pJRFk0TGpFMklERTBNQzQ1T1RNZ05qWXVOVFlnTVRRd0xqazVNeUEyTkM0M01rTXhOREF1T1RreklEWXlMamc0SURFME1TNDFPVE1nTmpFdU16SWdNVFF5TGpjNU15QTJNQzR3TkVNeE5EUXVNRGN6SURVNExqWTRJREUwTlM0Mk56TWdOVGdnTVRRM0xqVTVNeUExT0VNeE5Ea3VOVEV6SURVNElERTFNUzR3TnpNZ05UZ3VOamdnTVRVeUxqSTNNeUEyTUM0d05FTXhOVE11TlRVeklEWXhMak15SURFMU5DNHhPVE1nTmpJdU9EZ2dNVFUwTGpFNU15QTJOQzQzTWtNeE5UUXVNVGt6SURZMkxqVTJJREUxTXk0MU5UTWdOamd1TVRZZ01UVXlMakkzTXlBMk9TNDFNa014TlRFdU1EY3pJRGN3TGpnZ01UUTVMalV4TXlBM01TNDBOQ0F4TkRjdU5Ua3pJRGN4TGpRMFdpSWdabWxzYkQwaVlteGhZMnNpSUM4K1BIUmxlSFFnZUQwaU1qQWlJSGs5SWpFNE1DSWdabWxzYkQwaVlteGhZMnNpUGxSdmEyVnVJQ01nTVRZNE5qd3ZkR1Y0ZEQ0OEwzTjJaejQ9IiwgImF0dHJpYnV0ZXMiOiBbeyJ0cmFpdF90eXBlIjoiVHlwZSIsICJ2YWx1ZSI6ImRlZXBza3libHVlIn1dfQ=="
        expected_object = {
            "token": "1686",
            "image": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMDAiIGhlaWdodD0iMjAwIiB2aWV3Qm94PSIwIDAgMjAwIDIwMCIgc3R5bGU9ImJhY2tncm91bmQ6ZGVlcHNreWJsdWUiPjxwYXRoIGQ9Ik02OC40NCAxNDMuNDRDNjEuODggMTQzLjQ0IDU2LjA0IDE0MS44NCA1MC45MiAxMzguNjRDNDUuOCAxMzUuMzYgNDEuNzYgMTMwLjY4IDM4LjggMTI0LjZDMzUuODQgMTE4LjUyIDM0LjM2IDExMS4yIDM0LjM2IDEwMi42NEMzNC4zNiA5NC4xNiAzNS44NCA4Ni44OCAzOC44IDgwLjhDNDEuODQgNzQuNjQgNDUuOTYgNjkuOTYgNTEuMTYgNjYuNzZDNTYuNDQgNjMuNDggNjIuNDggNjEuODQgNjkuMjggNjEuODRDNzQuNDggNjEuODQgNzguODQgNjIuODggODIuMzYgNjQuOTZDODUuODggNjYuOTYgODguNzYgNjkuMTIgOTEgNzEuNDRMODUuMzYgNzcuOEM4My40NCA3NS43MiA4MS4yIDc0IDc4LjY0IDcyLjY0Qzc2LjE2IDcxLjI4IDczLjA0IDcwLjYgNjkuMjggNzAuNkM2NC40IDcwLjYgNjAuMTIgNzEuOTIgNTYuNDQgNzQuNTZDNTIuNzYgNzcuMTIgNDkuODggODAuNzYgNDcuOCA4NS40OEM0NS44IDkwLjIgNDQuOCA5NS44NCA0NC44IDEwMi40QzQ0LjggMTA5LjA0IDQ1Ljc2IDExNC43NiA0Ny42OCAxMTkuNTZDNDkuNiAxMjQuMzYgNTIuMzYgMTI4LjA4IDU1Ljk2IDEzMC43MkM1OS41NiAxMzMuMzYgNjMuOTIgMTM0LjY4IDY5LjA0IDEzNC42OEM3MS43NiAxMzQuNjggNzQuMzYgMTM0LjI4IDc2Ljg0IDEzMy40OEM3OS4zMiAxMzIuNiA4MS4yOCAxMzEuNDQgODIuNzIgMTMwVjEwOS40OEg2N1YxMDEuMkg5MS45NlYxMzQuMzJDODkuNDggMTM2Ljg4IDg2LjIgMTM5LjA0IDgyLjEyIDE0MC44Qzc4LjEyIDE0Mi41NiA3My41NiAxNDMuNDQgNjguNDQgMTQzLjQ0Wk0xMzUuOTUzIDE0My40NEMxMzAuODMzIDE0My40NCAxMjYuMDczIDE0Mi4yNCAxMjEuNjczIDEzOS44NEMxMTcuMzUzIDEzNy40NCAxMTMuODMzIDEzMy45NiAxMTEuMTEzIDEyOS40QzEwOC40NzMgMTI0Ljg0IDEwNy4xNTMgMTE5LjM2IDEwNy4xNTMgMTEyLjk2QzEwNy4xNTMgMTA2LjQgMTA4LjQ3MyAxMDAuODQgMTExLjExMyA5Ni4yOEMxMTMuODMzIDkxLjcyIDExNy4zNTMgODguMjQgMTIxLjY3MyA4NS44NEMxMjYuMDczIDgzLjQ0IDEzMC44MzMgODIuMjQgMTM1Ljk1MyA4Mi4yNEMxNDEuMDczIDgyLjI0IDE0NS43OTMgODMuNDQgMTUwLjExMyA4NS44NEMxNTQuNTEzIDg4LjI0IDE1OC4wMzMgOTEuNzIgMTYwLjY3MyA5Ni4yOEMxNjMuMzkzIDEwMC44NCAxNjQuNzUzIDEwNi40IDE2NC43NTMgMTEyLjk2QzE2NC43NTMgMTE5LjM2IDE2My4zOTMgMTI0Ljg0IDE2MC42NzMgMTI5LjRDMTU4LjAzMyAxMzMuOTYgMTU0LjUxMyAxMzcuNDQgMTUwLjExMyAxMzkuODRDMTQ1Ljc5MyAxNDIuMjQgMTQxLjA3MyAxNDMuNDQgMTM1Ljk1MyAxNDMuNDRaTTEzNS45NTMgMTM1LjI4QzEzOS43MTMgMTM1LjI4IDE0Mi45OTMgMTM0LjM2IDE0NS43OTMgMTMyLjUyQzE0OC41OTMgMTMwLjYgMTUwLjc1MyAxMjcuOTYgMTUyLjI3MyAxMjQuNkMxNTMuNzkzIDEyMS4yNCAxNTQuNTUzIDExNy4zNiAxNTQuNTUzIDExMi45NkMxNTQuNTUzIDEwOC40OCAxNTMuNzkzIDEwNC41NiAxNTIuMjczIDEwMS4yQzE1MC43NTMgOTcuNzYgMTQ4LjU5MyA5NS4xMiAxNDUuNzkzIDkzLjI4QzE0Mi45OTMgOTEuMzYgMTM5LjcxMyA5MC40IDEzNS45NTMgOTAuNEMxMzIuMTkzIDkwLjQgMTI4LjkxMyA5MS4zNiAxMjYuMTEzIDkzLjI4QzEyMy4zOTMgOTUuMTIgMTIxLjIzMyA5Ny43NiAxMTkuNjMzIDEwMS4yQzExOC4xMTMgMTA0LjU2IDExNy4zNTMgMTA4LjQ4IDExNy4zNTMgMTEyLjk2QzExNy4zNTMgMTE3LjM2IDExOC4xMTMgMTIxLjI0IDExOS42MzMgMTI0LjZDMTIxLjIzMyAxMjcuOTYgMTIzLjM5MyAxMzAuNiAxMjYuMTEzIDEzMi41MkMxMjguOTEzIDEzNC4zNiAxMzIuMTkzIDEzNS4yOCAxMzUuOTUzIDEzNS4yOFpNMTI0LjMxMyA3MS40NEMxMjIuMzkzIDcxLjQ0IDEyMC43OTMgNzAuOCAxMTkuNTEzIDY5LjUyQzExOC4zMTMgNjguMTYgMTE3LjcxMyA2Ni41NiAxMTcuNzEzIDY0LjcyQzExNy43MTMgNjIuODggMTE4LjMxMyA2MS4zMiAxMTkuNTEzIDYwLjA0QzEyMC43OTMgNTguNjggMTIyLjM5MyA1OCAxMjQuMzEzIDU4QzEyNi4yMzMgNTggMTI3Ljc5MyA1OC42OCAxMjguOTkzIDYwLjA0QzEzMC4yNzMgNjEuMzIgMTMwLjkxMyA2Mi44OCAxMzAuOTEzIDY0LjcyQzEzMC45MTMgNjYuNTYgMTMwLjI3MyA2OC4xNiAxMjguOTkzIDY5LjUyQzEyNy43OTMgNzAuOCAxMjYuMjMzIDcxLjQ0IDEyNC4zMTMgNzEuNDRaTTE0Ny41OTMgNzEuNDRDMTQ1LjY3MyA3MS40NCAxNDQuMDczIDcwLjggMTQyLjc5MyA2OS41MkMxNDEuNTkzIDY4LjE2IDE0MC45OTMgNjYuNTYgMTQwLjk5MyA2NC43MkMxNDAuOTkzIDYyLjg4IDE0MS41OTMgNjEuMzIgMTQyLjc5MyA2MC4wNEMxNDQuMDczIDU4LjY4IDE0NS42NzMgNTggMTQ3LjU5MyA1OEMxNDkuNTEzIDU4IDE1MS4wNzMgNTguNjggMTUyLjI3MyA2MC4wNEMxNTMuNTUzIDYxLjMyIDE1NC4xOTMgNjIuODggMTU0LjE5MyA2NC43MkMxNTQuMTkzIDY2LjU2IDE1My41NTMgNjguMTYgMTUyLjI3MyA2OS41MkMxNTEuMDczIDcwLjggMTQ5LjUxMyA3MS40NCAxNDcuNTkzIDcxLjQ0WiIgZmlsbD0iYmxhY2siIC8+PHRleHQgeD0iMjAiIHk9IjE4MCIgZmlsbD0iYmxhY2siPlRva2VuICMgMTY4NjwvdGV4dD48L3N2Zz4=",
            "attributes": [{"trait_type": "Type", "value": "deepskyblue"}],
        }

        self.assertEqual(
            collectibles_service._retrieve_metadata_from_uri(uri),
            expected_object,
        )

        # Test not valid b64 encoded uri
        uri = "data:application/json;base64,eyJ0b2tlbiI6"
        with self.assertRaisesMessage(MetadataRetrievalException, uri):
            collectibles_service._retrieve_metadata_from_uri(uri)
