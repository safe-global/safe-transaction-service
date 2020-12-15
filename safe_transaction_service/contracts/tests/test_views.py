import logging

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from .factories import ContractFactory

logger = logging.getLogger(__name__)


class TestContractViews(APITestCase):
    def test_contract_view(self):
        contract_address = Account.create().address
        response = self.client.get(reverse('v1:contract', args=(contract_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        contract = ContractFactory(address=contract_address)
        response = self.client.get(reverse('v1:contract', args=(contract_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'address': contract.address,
            'name': contract.name,
            'contract_abi': {
                'abi': contract.contract_abi.abi,
                'description': contract.contract_abi.description,
                'relevance': contract.contract_abi.relevance,
            }
        })

        contract.contract_abi = None
        contract.save(update_fields=['contract_abi'])
        response = self.client.get(reverse('v1:contract', args=(contract_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'address': contract.address,
            'name': contract.name,
            'contract_abi': None
        })

    def test_contracts_view(self):
        contract_address = Account.create().address
        response = self.client.get(reverse('v1:contracts'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['results'], [])

        contract = ContractFactory(address=contract_address)
        response = self.client.get(reverse('v1:contracts'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'], [{
            'address': contract.address,
            'name': contract.name,
            'contract_abi': {
                'abi': contract.contract_abi.abi,
                'description': contract.contract_abi.description,
                'relevance': contract.contract_abi.relevance,
            }
        }])

        ContractFactory()
        response = self.client.get(reverse('v1:contracts'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
