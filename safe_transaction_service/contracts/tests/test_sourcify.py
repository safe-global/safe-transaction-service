from typing import List

from django.test import TestCase

from ..sourcify import Sourcify


class TestSourcify(TestCase):
    def test_get_contract_metadata(self):
        sourcify = Sourcify()
        safe_contract_address = '0x6851D6fDFAfD08c0295C392436245E5bc78B0185'
        contract_metadata = sourcify.get_contract_metadata(safe_contract_address)
        self.assertEqual(contract_metadata.name, 'GnosisSafe')
        self.assertIsInstance(contract_metadata.abi, List)
        self.assertTrue(contract_metadata.abi)
        contract_metadata_rinkeby = sourcify.get_contract_metadata(safe_contract_address, network_id=4)
        self.assertEqual(contract_metadata, contract_metadata_rinkeby)
