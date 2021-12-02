import logging
from urllib.parse import urljoin

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from .factories import ContractFactory

logger = logging.getLogger(__name__)


class TestContractViews(APITestCase):
    def _build_full_file_url(self, path: str):
        return urljoin("http://testserver/", path)

    def test_contract_view(self):
        contract_address = "0x"  # Invalid format
        response = self.client.get(
            reverse("v1:contracts:detail", args=(contract_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        contract_address = Account.create().address
        response = self.client.get(
            reverse("v1:contracts:detail", args=(contract_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        contract = ContractFactory(address=contract_address)
        response = self.client.get(
            reverse("v1:contracts:detail", args=(contract_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "address": contract.address,
                "name": contract.name,
                "display_name": contract.display_name,
                "logo_uri": self._build_full_file_url(contract.logo.url),
                "contract_abi": {
                    "abi": contract.contract_abi.abi,
                    "description": contract.contract_abi.description,
                    "relevance": contract.contract_abi.relevance,
                },
                "trusted_for_delegate_call": False,
            },
        )

        display_name = "SharinganContract"
        contract.contract_abi = None
        contract.display_name = display_name
        contract.logo = None
        contract.save()
        response = self.client.get(
            reverse("v1:contracts:detail", args=(contract_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "address": contract.address,
                "name": contract.name,
                "display_name": display_name,
                "logo_uri": None,
                "contract_abi": None,
                "trusted_for_delegate_call": False,
            },
        )

    def test_contracts_view(self):
        contract_address = Account.create().address
        response = self.client.get(reverse("v1:contracts:list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        contract = ContractFactory(address=contract_address)
        response = self.client.get(reverse("v1:contracts:list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["results"],
            [
                {
                    "address": contract.address,
                    "name": contract.name,
                    "display_name": contract.display_name,
                    "logo_uri": self._build_full_file_url(contract.logo.url),
                    "contract_abi": {
                        "abi": contract.contract_abi.abi,
                        "description": contract.contract_abi.description,
                        "relevance": contract.contract_abi.relevance,
                    },
                    "trusted_for_delegate_call": False,
                }
            ],
        )

        ContractFactory(contract_abi__abi=[])
        response = self.client.get(reverse("v1:contracts:list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
