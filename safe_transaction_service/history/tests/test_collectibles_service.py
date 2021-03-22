from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account

from gnosis.eth import EthereumClient
from gnosis.eth.ethereum_client import (Erc721Info, Erc721Manager,
                                        EthereumClientProvider,
                                        InvalidERC721Info)
from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ...tokens.constants import ENS_CONTRACTS_WITH_TLD
from ..services import CollectiblesService
from ..services.collectibles_service import (Collectible,
                                             CollectibleWithMetadata,
                                             Erc721InfoWithLogo)
from .factories import EthereumEventFactory
from .utils import just_test_if_mainnet_node


class TestCollectiblesService(EthereumTestCaseMixin, TestCase):
    def test_get_collectibles(self):
        self.maxDiff = None
        mainnet_node = just_test_if_mainnet_node()
        ethereum_client = EthereumClient(mainnet_node)
        EthereumClientProvider.instance = ethereum_client
        collectibles_service = CollectiblesService(ethereum_client)

        # Caches empty
        self.assertFalse(collectibles_service.cache_token_info)
        self.assertFalse(collectibles_service.cache_uri_metadata)

        safe_address = '0xfF501B324DC6d78dC9F983f140B9211c3EdB4dc7'
        ens_address = '0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85'
        ens_logo_uri = 'https://gnosis-safe-token-logos.s3.amazonaws.com/ENS.png'
        ens_token_id = 93288724337340885726942883352789513739931149355867373088241393067029827792979
        dappcon_2020_address = '0x202d2f33449Bf46d6d32Ae7644aDA130876461a4'
        dappcon_token_id = 13
        dappcon_logo_uri = Token(address=dappcon_2020_address, name='', symbol='').get_full_logo_uri()
        self.assertEqual(collectibles_service.get_collectibles(safe_address), [])

        erc721_addresses = [(dappcon_2020_address, dappcon_token_id),
                            (ens_address, ens_token_id),  # ENS
                            ]

        for erc721_address, token_id in erc721_addresses:
            EthereumEventFactory(erc721=True, to=safe_address, address=erc721_address, value=token_id)

        expected = [Collectible(token_name='Ethereum Name Service',
                                token_symbol='ENS',
                                logo_uri=ens_logo_uri,
                                address=ens_address,
                                id=ens_token_id,
                                uri=None),
                    Collectible(token_name='DappCon2020',
                                token_symbol='D20',
                                logo_uri=dappcon_logo_uri,
                                address=dappcon_2020_address,
                                id=dappcon_token_id,
                                uri='https://us-central1-thing-1d2be.cloudfunctions.net/getThing?thingId=Q1c8y3PwYomxjW25sW3l')]
        collectibles = collectibles_service.get_collectibles(safe_address)
        self.assertEqual(len(collectibles), len(expected))
        self.assertEqual(collectibles, expected)

        expected = [CollectibleWithMetadata(token_name='Ethereum Name Service',
                                            token_symbol='ENS',
                                            logo_uri=ens_logo_uri,
                                            address=ens_address,
                                            id=93288724337340885726942883352789513739931149355867373088241393067029827792979,
                                            uri=None,
                                            metadata={'name': 'safe-multisig.eth', 'description': '.eth ENS Domain', 'image': 'https://gnosis-safe-token-logos.s3.amazonaws.com/ENS.png'}),
                    CollectibleWithMetadata(token_name='DappCon2020',
                                            token_symbol='D20',
                                            logo_uri=dappcon_logo_uri,
                                            address=dappcon_2020_address,
                                            id=13,
                                            uri='https://us-central1-thing-1d2be.cloudfunctions.net/getThing?thingId=Q1c8y3PwYomxjW25sW3l',
                                            metadata={'minted': 'Minted on Mintbase.io', 'image': 'https://firebasestorage.googleapis.com/v0/b/thing-1d2be.appspot.com/o/token%2Fasset-1581932081565?alt=media&token=57b47904-1782-40e0-ab6d-4f8ca82e6884', 'name': 'Earlybird Ticket', 'forSale': False, 'minter': '', 'external_url': 'https://mintbase.io/my-market/0x202d2f33449bf46d6d32ae7644ada130876461a4', 'fiatPrice': '$278.66', 'tags': [], 'mintedOn': {'_seconds': 1581932237, '_nanoseconds': 580000000}, 'amountToMint': 10, 'contractAddress': '0x202d2f33449bf46d6d32ae7644ada130876461a4', 'type': 'ERC721', 'attributes': [{'display_type': 'date', 'value': 1599516000, 'trait_type': 'Start Date'}, {'display_type': 'date', 'value': 1599688800, 'trait_type': 'End Date'}, {'value': 'Holzmarktstraße 33, 10243 Berlin, Germany', 'trait_type': 'location'}, {'value': 'ChIJhz8mADlOqEcR2lw7-iNCoDM', 'trait_type': 'place_id'}, {'value': 'https://dappcon.io/', 'trait_type': 'website'}], 'price': '1.1', 'description': 'This NFT ticket gives you full access to the 3-day conference. \nDate: 8 - 10 September *** Location: Holzmarktstraße 33 I 10243 Berlin', 'numAvailable': 0}
                                            )]
        collectibles_with_metadata = collectibles_service.get_collectibles_with_metadata(safe_address)
        self.assertEqual(collectibles_with_metadata, expected)

        # Set ens trusted
        Token.objects.filter(address=ens_address).update(trusted=True)
        collectibles_with_metadata = collectibles_service.get_collectibles_with_metadata(safe_address,
                                                                                         only_trusted=True)
        self.assertEqual(collectibles_with_metadata, expected[:1])

        # Set ens spam
        Token.objects.filter(address=ens_address).update(trusted=False, spam=True)
        collectibles_with_metadata = collectibles_service.get_collectibles_with_metadata(safe_address,
                                                                                         exclude_spam=True)
        self.assertEqual(collectibles_with_metadata, expected[1:])

        # Caches not empty
        self.assertTrue(collectibles_service.cache_token_info)
        self.assertTrue(collectibles_service.cache_uri_metadata)
        del EthereumClientProvider.instance

    @mock.patch.object(Erc721Manager, 'get_info', autospec=True)
    def test_get_token_info(self, get_info_mock: MagicMock):
        collectibles_service = CollectiblesService(self.ethereum_client)
        random_address = Account.create().address

        # No DB, no blockchain source
        get_info_mock.side_effect = InvalidERC721Info
        self.assertFalse(collectibles_service.cache_token_info)
        self.assertIsNone(collectibles_service.get_token_info(random_address))
        self.assertTrue(collectibles_service.cache_token_info)  # Cache works for not found tokens too

        # Add DB source
        token = TokenFactory()
        self.assertEqual(collectibles_service.get_token_info(token.address), Erc721InfoWithLogo.from_token(token))

        # Just Blockchain source
        random_address = Account.create().address
        self.assertEqual(Token.objects.count(), 1)
        get_info_mock.side_effect = None
        get_info_mock.return_value = Erc721Info('Uxio Collectible Card', 'UCC')
        token_info = collectibles_service.get_token_info(random_address)
        self.assertIsInstance(token_info, Erc721InfoWithLogo)
        self.assertEqual(token_info.name, get_info_mock.return_value.name)
        self.assertEqual(token_info.symbol, get_info_mock.return_value.symbol)
        self.assertEqual(Token.objects.count(), 2)

        # Test switch name-symbol when symbol is way longer than name
        random_address = Account.create().address
        get_info_mock.return_value = Erc721Info('POAP', 'The Proof of Attendance Protocol')
        token_info = collectibles_service.get_token_info(random_address)
        self.assertIsInstance(token_info, Erc721InfoWithLogo)
        self.assertEqual(token_info.symbol, get_info_mock.return_value.name)
        self.assertEqual(token_info.name, get_info_mock.return_value.symbol)
        self.assertEqual(Token.objects.count(), 3)
        self.assertEqual(len(collectibles_service.cache_token_info), 4)  # Cache works for not found tokens too

        # Test ENS (hardcoded)
        get_info_mock.return_value = None
        token_info = collectibles_service.get_token_info(list(ENS_CONTRACTS_WITH_TLD.keys())[0])
        self.assertIsNotNone(token_info)
        self.assertEqual(Token.objects.count(), 4)

    @mock.patch.object(Erc721Manager, 'get_token_uris', autospec=True)
    def test_get_token_uris(self, get_token_uris_mock: MagicMock):
        token_uris = ['http://testing.com/12', None, '']
        get_token_uris_mock.return_value = token_uris
        addresses_with_token_ids = [(Account.create(), i) for i in range(3)]
        collectibles_service = CollectiblesService(self.ethereum_client)
        self.assertFalse(collectibles_service.cache_token_uri)
        collectibles_service.get_token_uris(addresses_with_token_ids)

        # Test cache
        self.assertEqual(len(collectibles_service.cache_token_uri), 3)
        get_token_uris_mock.return_value = []
        for address_with_token_id, token_uri in zip(addresses_with_token_ids, token_uris):
            self.assertEqual(collectibles_service.cache_token_uri[address_with_token_id], token_uri)

    def test_retrieve_metadata_from_uri(self):
        collectibles_service = CollectiblesService(self.ethereum_client)
        # Test ipfs
        ipfs_address = 'ipfs://ipfs/Qmc4ZMDNMu5bguGohtGQGx5DQexitnNvf5Rb7Yzbja47bo'
        expected_object = {
            'description': 'Flamingo DAO Initial Token',
            'name': 'Flamingo DAO',
            'image': 'https://ipfs.io/ipfs/QmXKU5RBTrGaYn5M1iWQaeKuCKV34g417YDGN5Yh7Uxk4i'
        }

        self.assertEqual(collectibles_service._retrieve_metadata_from_uri(ipfs_address), expected_object)
