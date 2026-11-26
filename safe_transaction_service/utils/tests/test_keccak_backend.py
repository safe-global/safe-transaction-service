# SPDX-License-Identifier: FSL-1.1-MIT
from django.test import SimpleTestCase

import safe_eth_native
from eth_hash.auto import keccak
from web3 import Web3


class TestKeccakBackend(SimpleTestCase):
    def test_eth_hash_uses_native_keccak(self):
        """
        web3, eth-utils and eth-account hash with the native keccak256 of safe-eth-py.
        Any `ETH_HASH_BACKEND` value makes them use an eth-hash backend instead
        """
        Web3.keccak(b"")
        self.assertIs(keccak.hasher, safe_eth_native.keccak256)
