from django.test import TestCase

from gnosis.eth.ethereum_client import EthereumNetwork

from ..clients.blockscout_client import (BlockscoutClient,
                                         BlockScoutConfigurationProblem)
from .mocks import sourcify_safe_metadata


class TestBlockscoutClient(TestCase):
    def test_blockscout_client(self):
        with self.assertRaises(BlockScoutConfigurationProblem):
            BlockscoutClient(EthereumNetwork.MAINNET)

        blockscout_client = BlockscoutClient(EthereumNetwork.XDAI)
        safe_master_copy_abi = sourcify_safe_metadata['output']['abi']
        safe_master_copy_address = '0x6851D6fDFAfD08c0295C392436245E5bc78B0185'
        contract_metadata = blockscout_client.get_contract_metadata(safe_master_copy_address)
        self.assertEqual(contract_metadata.name, 'GnosisSafe')
        self.assertEqual(contract_metadata.abi, safe_master_copy_abi)
        random_address = '0xaE32496491b53841efb51829d6f886387708F99a'
        self.assertIsNone(blockscout_client.get_contract_metadata(random_address))
