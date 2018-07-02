from django.conf import settings
from django.test import TestCase
from ethereum import utils
from faker import Faker

from ..signing import EthereumSignedMessage, EthereumSigner
from .factories import get_eth_address_with_key

faker = Faker()


class TestSigning(TestCase):

    def test_ethereum_signer(self):
        eth_address, eth_key = get_eth_address_with_key()
        eth_address_bad_checksum = eth_address.lower()

        message = faker.name()
        prefix = faker.name()
        ethereum_signer = EthereumSigner(message, eth_key, hash_prefix=prefix)

        self.assertEqual(ethereum_signer.hash_prefix, prefix)
        self.assertEqual(ethereum_signer.message_hash, utils.sha3(prefix + message))
        self.assertEqual(ethereum_signer.get_signing_address(), eth_address)
        self.assertTrue(ethereum_signer.check_signing_address(eth_address_bad_checksum))

    def test_ethereum_signed_message(self):
        eth_address, eth_key = get_eth_address_with_key()
        eth_address_bad_checksum = eth_address.lower()

        prefix = settings.ETH_HASH_PREFIX
        message = faker.name()
        prefixed_message = prefix + message
        message_hash = utils.sha3(prefixed_message)
        v, r, s = utils.ecsign(message_hash, eth_key)
        ethereum_signed_message = EthereumSignedMessage(message, v, r, s)

        self.assertTrue(ethereum_signed_message.check_message_hash(message))

        self.assertTrue(ethereum_signed_message.check_signing_address(eth_address))
        self.assertTrue(ethereum_signed_message.check_signing_address(eth_address.lower()))
        self.assertTrue(ethereum_signed_message.check_signing_address(eth_address[2:]))
        self.assertTrue(ethereum_signed_message.check_signing_address(eth_address_bad_checksum))

        self.assertEqual(ethereum_signed_message.get_signing_address(), eth_address)
        self.assertTrue(utils.check_checksum(ethereum_signed_message.get_signing_address()))
