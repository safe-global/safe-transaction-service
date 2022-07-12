from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from .factories import ERC721TransferFactory, SafeContractFactory


class TestViewsV2(SafeTestCaseMixin, APITestCase):
    def test_safe_collectibles_paginated(self):
        safe_address = Account.create().address

        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        token_address = Account.create().address

        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        # Insert ERC721 on DB
        erc721_list = [
            ERC721TransferFactory(
                address=token_address, token_id=token_id, to=safe_address
            )
            for token_id in range(1, 12)
        ]

        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,)) + "?limit=20",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 11)
        self.assertEqual(len(response.data["results"]), 10)  # Max limit is 10

        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=5&offset=0",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 11)
        self.assertEqual(len(response.data["results"]), 5)
        next = (
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=5&offset=5"
        )
        self.assertIn(next, response.data["next"])
        self.assertEqual(response.data["previous"], None)
        for result, erc721 in zip(response.data["results"], erc721_list[0:5]):
            self.assertEqual(result["address"], erc721.address)
            self.assertEqual(int(result["id"]), erc721.token_id)

        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=5&offset=5",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 11)
        self.assertEqual(len(response.data["results"]), 5)
        next = (
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=5&offset=10"
        )
        previous = (
            reverse("v2:history:safe-collectibles", args=(safe_address,)) + "?limit=5"
        )
        self.assertIn(next, response.data["next"])
        self.assertIn(previous, response.data["previous"])
        for result, erc721 in zip(response.data["results"], erc721_list[5:10]):
            self.assertEqual(result["address"], erc721.address)
            self.assertEqual(int(result["id"]), erc721.token_id)

        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=5&offset=10",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 11)
        self.assertEqual(len(response.data["results"]), 1)
        previous = (
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=5&offset=5"
        )
        self.assertEqual(response.data["next"], None)
        self.assertIn(previous, response.data["previous"])
        for result, erc721 in zip(response.data["results"], erc721_list[10:]):
            self.assertEqual(result["address"], erc721.address)
            self.assertEqual(int(result["id"]), erc721.token_id)

        # Check results are sorted
        # Null address should be first, FF... address should be last
        erc721_null = ERC721TransferFactory(
            address=NULL_ADDRESS, token_id=0, to=safe_address
        )
        erc721_full = ERC721TransferFactory(
            address="0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            token_id=5,
            to=safe_address,
        )
        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=1&offset=0",
            format="json",
        )
        self.assertEqual(response.data["results"][0]["address"], erc721_null.address)
        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=1&offset=12",
            format="json",
        )
        self.assertEqual(response.data["results"][0]["address"], erc721_full.address)

        # Check if results are sorted by address and token_id
        erc721_full_previous = ERC721TransferFactory(
            address="0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF",
            token_id=1,
            to=safe_address,
        )
        response = self.client.get(
            reverse("v2:history:safe-collectibles", args=(safe_address,))
            + "?limit=2&offset=12",
            format="json",
        )
        self.assertEqual(
            response.data["results"][0]["address"], erc721_full_previous.address
        )
        self.assertEqual(
            int(response.data["results"][0]["id"]), erc721_full_previous.token_id
        )
        self.assertEqual(response.data["results"][1]["address"], erc721_full.address)
        self.assertEqual(int(response.data["results"][1]["id"]), erc721_full.token_id)
