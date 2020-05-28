from django.test import TestCase

from gnosis.eth import EthereumClient

from ..services import CollectiblesService
from ..services.collectibles_service import (Collectible,
                                             CollectibleWithMetadata)
from .factories import EthereumEventFactory
from .utils import just_test_if_mainnet_node


class TestCollectiblesService(TestCase):
    def test_get_collectibles(self):
        mainnet_node = just_test_if_mainnet_node()
        ethereum_client = EthereumClient(mainnet_node)
        collectibles_service = CollectiblesService(ethereum_client)

        safe_address = '0xfF501B324DC6d78dC9F983f140B9211c3EdB4dc7'
        self.assertEqual(collectibles_service.get_collectibles(safe_address), [])

        erc721_addresses = [('0x202d2f33449Bf46d6d32Ae7644aDA130876461a4', 13),
                            ('0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85', 93288724337340885726942883352789513739931149355867373088241393067029827792979),  # ENS
                            ]

        for erc721_address, token_id in erc721_addresses:
            EthereumEventFactory(erc721=True, to=safe_address, address=erc721_address, value=token_id)

        expected = [Collectible(token_name='Ethereum Name Service', token_symbol='ENS',
                                address='0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85',
                                id=93288724337340885726942883352789513739931149355867373088241393067029827792979,
                                uri=None),
                    Collectible(token_name='DappCon2020', token_symbol='D20',
                                address='0x202d2f33449Bf46d6d32Ae7644aDA130876461a4',
                                id=13,
                                uri='https://us-central1-thing-1d2be.cloudfunctions.net/getThing?thingId=Q1c8y3PwYomxjW25sW3l')]
        collectibles = collectibles_service.get_collectibles(safe_address)
        self.assertEqual(len(collectibles), len(expected))
        self.assertEqual(collectibles, expected)

        expected = [CollectibleWithMetadata(token_name='Ethereum Name Service', token_symbol='ENS',
                                            address='0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85',
                                            id=93288724337340885726942883352789513739931149355867373088241393067029827792979,
                                            uri=None,
                                            metadata={'name': 'safe-multisig.eth', 'description': '.eth ENS Domain', 'image': 'https://gnosis-safe-token-logos.s3.amazonaws.com/ENS.png'}),
                    CollectibleWithMetadata(token_name='DappCon2020',
                                            token_symbol='D20', address='0x202d2f33449Bf46d6d32Ae7644aDA130876461a4',
                                            id=13,
                                            uri='https://us-central1-thing-1d2be.cloudfunctions.net/getThing?thingId=Q1c8y3PwYomxjW25sW3l',
                                            metadata={'minted': 'Minted on Mintbase.io', 'image': 'https://firebasestorage.googleapis.com/v0/b/thing-1d2be.appspot.com/o/token%2Fasset-1581932081565?alt=media&token=57b47904-1782-40e0-ab6d-4f8ca82e6884', 'name': 'Earlybird Ticket', 'forSale': False, 'minter': '', 'external_url': 'https://mintbase.io/my-market/0x202d2f33449bf46d6d32ae7644ada130876461a4', 'fiatPrice': '$278.66', 'tags': [], 'mintedOn': {'_seconds': 1581932237, '_nanoseconds': 580000000}, 'amountToMint': 10, 'contractAddress': '0x202d2f33449bf46d6d32ae7644ada130876461a4', 'type': 'ERC721', 'attributes': [{'display_type': 'date', 'value': 1599516000, 'trait_type': 'Start Date'}, {'display_type': 'date', 'value': 1599688800, 'trait_type': 'End Date'}, {'value': 'Holzmarktstraße 33, 10243 Berlin, Germany', 'trait_type': 'location'}, {'value': 'ChIJhz8mADlOqEcR2lw7-iNCoDM', 'trait_type': 'place_id'}, {'value': 'https://dappcon.io/', 'trait_type': 'website'}], 'price': '1.1', 'description': 'This NFT ticket gives you full access to the 3-day conference. \nDate: 8 - 10 September *** Location: Holzmarktstraße 33 I 10243 Berlin', 'numAvailable': 0}
                                            )]
        collectibles_with_metadata = collectibles_service.get_collectibles_with_metadata(safe_address)
        self.assertEqual(collectibles_with_metadata, expected)
