from rest_framework.test import APITestCase

from safe_transaction_history.ether.tests.factories import get_eth_address_with_key, get_transaction_with_info
from ..serializers import BaseSafeMultisigTransactionSerializer, SafeMultisigHistorySerializer


class TestViews(APITestCase):

    def test_base_safe_multisig_transaction_serializer(self):
        safe_address, _ = get_eth_address_with_key()
        owner, _ = get_eth_address_with_key()
        recipient, _ = get_eth_address_with_key()
        transaction_hash, transaction_data = get_transaction_with_info()

        transaction_data.update({
            'safe': safe_address,
            'operation': 0,
            'contract_transaction_hash': '0x0',
            'sender': transaction_data['from']
        })

        invalid_serializer = BaseSafeMultisigTransactionSerializer(data=transaction_data)
        self.assertFalse(invalid_serializer.is_valid())

        transaction_data.update({
            'safe': safe_address,
            'operation': 0,
            'contract_transaction_hash': '0x' + transaction_hash,
            'sender': transaction_data['from']
        })

        serializer = BaseSafeMultisigTransactionSerializer(data=transaction_data)
        self.assertTrue(serializer.is_valid())
