import logging

from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from hexbytes import HexBytes

from .factories import generate_valid_s
from safe_transaction_history.ether.utils import NULL_ADDRESS
from safe_transaction_history.ether.tests.factories import (get_transaction_with_info, get_eth_address_with_key)
from ..contracts import get_safe_team_contract
from ..safe_creation_tx import SafeCreationTx
from ..serializers import BaseSafeMultisigTransactionSerializer, SafeMultisigHistorySerializer
from .safe_test_case import TestCaseWithSafeContractMixin


logger = logging.getLogger(__name__)
GAS_PRICE = settings.SAFE_GAS_PRICE
LOG_TITLE_WIDTH=100


class TestViews(APITestCase, TestCaseWithSafeContractMixin):

    @classmethod
    def setUpTestData(cls):
        cls.prepare_safe_tests()

    def test_about(self):
        request = self.client.get(reverse('v1:about'))
        self.assertEqual(request.status_code, status.HTTP_200_OK)

    def test_multisig_transaction_creation(self):
        w3 = self.w3

        safe_address, _ = get_eth_address_with_key()
        # Generate transaction
        transaction_hash, transaction_data = get_transaction_with_info()

        transaction_data.update({
            'safe': safe_address,
            'operation': 0,
            'contract_transaction_hash': '0x' + transaction_hash,
            'sender': transaction_data['from']
        })

        invalid_transaction_data = transaction_data.copy()
        invalid_transaction_data['contract_transaction_hash'] = '0x0' # invaid hash

        serializer = BaseSafeMultisigTransactionSerializer(data=invalid_transaction_data)
        self.assertFalse(serializer.is_valid())
        request = self.client.post(reverse('v1:create-multisig-transactions', kwargs={'address': safe_address}),
                                   data=serializer.data, format='json')
        self.assertEquals(request.status_code, status.HTTP_400_BAD_REQUEST)


        # Create Safe on blockchain
        s = generate_valid_s()
        funder = w3.eth.accounts[1]
        owners = w3.eth.accounts[2:6]
        threshold = len(owners) - 1
        gas_price = GAS_PRICE

        logger.info("Test Safe Proxy creation without payment".center(LOG_TITLE_WIDTH, '-'))

        safe_builder = SafeCreationTx(w3=w3,
                                      owners=owners,
                                      threshold=threshold,
                                      signature_s=s,
                                      master_copy=self.safe_personal_contract_address,
                                      gas_price=gas_price,
                                      funder=NULL_ADDRESS)

        response = w3.eth.sendTransaction({
            'from': funder,
            'to': safe_builder.deployer_address,
            'value': safe_builder.payment
        })

        logger.info("Create proxy contract with address %s", safe_builder.safe_address)

        tx_hash = w3.eth.sendRawTransaction(safe_builder.raw_tx)
        tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
        safe_address = tx_receipt.contractAddress

        self.assertEqual(tx_receipt.contractAddress, safe_builder.safe_address)

        deployed_safe_proxy_contract = get_safe_team_contract(w3, safe_address)

        logger.info("Deployer account has still %d gwei left (will be lost)",
                    w3.fromWei(w3.eth.getBalance(safe_builder.deployer_address), 'gwei'))

        self.assertEqual(deployed_safe_proxy_contract.functions.getThreshold().call(), threshold)
        self.assertEqual(deployed_safe_proxy_contract.functions.getOwners().call(), owners)


        # TODO review
        transaction_data = {
            'sender': funder,
            'to': safe_builder.deployer_address,
            'value': safe_builder.payment,
            'safe': safe_address,
            'operation': 0,
            'nonce': 0,
            'data': HexBytes(0x0),
            'contract_transaction_hash': tx_hash.hex()
        }

        serializer = BaseSafeMultisigTransactionSerializer(data=transaction_data)
        self.assertTrue(serializer.is_valid())

        request = self.client.post(reverse('v1:create-multisig-transactions', kwargs={'address': safe_address}),
                                   data=serializer.data, format='json')
        self.assertEquals(request.status_code, status.HTTP_201_CREATED)

    def test_get_multisig_transaction(self):
        pass