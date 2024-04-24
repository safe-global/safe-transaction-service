from unittest import mock

from django.urls import reverse

from eth_account import Account
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.signatures import signature_to_bytes
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..helpers import DelegateSignatureHelperV2
from ..models import SafeContractDelegate
from .factories import (
    ERC721TransferFactory,
    SafeContractDelegateFactory,
    SafeContractFactory,
)


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

    def test_delegates_post(self):
        url = reverse("v2:history:delegates")
        safe_address = Account.create().address
        delegate = Account.create()
        delegator = Account.create()
        label = "Saul Goodman"
        data = {
            "delegate": delegate.address,
            "delegator": delegator.address,
            "label": label,
            "signature": "0x" + "1" * 130,
        }
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            "Signature does not match provided delegator",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data["safe"] = safe_address
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            f"Safe={safe_address} does not exist", response.data["non_field_errors"][0]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        SafeContractFactory(address=safe_address)
        with mock.patch(
            "safe_transaction_service.history.serializers.get_safe_owners",
            return_value=[Account.create().address],
        ) as get_safe_owners_mock:
            response = self.client.post(url, format="json", data=data)
            self.assertIn(
                f"Provided delegator={delegator.address} is not an owner of Safe={safe_address}",
                response.data["non_field_errors"][0],
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            get_safe_owners_mock.return_value = [delegator.address]
            response = self.client.post(url, format="json", data=data)
            self.assertIn(
                f"Signature does not match provided delegator={delegator.address}",
                response.data["non_field_errors"][0],
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # Create delegate
            self.assertEqual(SafeContractDelegate.objects.count(), 0)
            chain_id = self.ethereum_client.get_chain_id()
            hash_to_sign = DelegateSignatureHelperV2.calculate_hash(
                delegate.address, chain_id, False
            )
            data["signature"] = delegator.signHash(hash_to_sign)["signature"].hex()
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertEqual(safe_contract_delegate.delegate, delegate.address)
            self.assertEqual(safe_contract_delegate.delegator, delegator.address)
            self.assertEqual(safe_contract_delegate.label, label)
            self.assertEqual(safe_contract_delegate.safe_contract_id, safe_address)

            # Update label
            label = "Jimmy McGill"
            data["label"] = label
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(SafeContractDelegate.objects.count(), 1)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertEqual(safe_contract_delegate.label, label)

        # Create delegate without a Safe
        hash_to_sign = DelegateSignatureHelperV2.calculate_hash(
            delegate.address, chain_id, False
        )
        data = {
            "label": "Kim Wexler",
            "delegate": delegate.address,
            "delegator": delegator.address,
            "signature": delegator.signHash(hash_to_sign)["signature"].hex(),
        }
        response = self.client.post(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)

        # Test bad request with an invalid signature
        signature = signature_to_bytes(0, int(delegator.address, 16), 65) + HexBytes(
            "0" * 65
        )
        data["signature"] = signature.hex()
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            f"Signature of type=CONTRACT_SIGNATURE for signer={delegator.address} is not valid",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delegates_get(self):
        url = reverse("v2:history:delegates")
        response = self.client.get(url, format="json")
        self.assertEqual(response.data[0], "At least one query param must be provided")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        delegator = Account.create().address

        # Add 2 delegates for the same Safe and delegator and another for a different Safe
        safe_contract_delegate_1 = SafeContractDelegateFactory(delegator=delegator)
        safe_contract = safe_contract_delegate_1.safe_contract
        safe_contract_delegate_2 = SafeContractDelegateFactory(
            safe_contract=safe_contract, delegator=delegator
        )
        safe_contract_delegate_3 = SafeContractDelegateFactory(
            delegate=safe_contract_delegate_1.delegate
        )

        expected = [
            {
                "delegate": safe_contract_delegate_1.delegate,
                "delegator": safe_contract_delegate_1.delegator,
                "label": safe_contract_delegate_1.label,
                "safe": safe_contract.address,
            },
            {
                "delegate": safe_contract_delegate_2.delegate,
                "delegator": safe_contract_delegate_2.delegator,
                "label": safe_contract_delegate_2.label,
                "safe": safe_contract.address,
            },
        ]
        response = self.client.get(
            url + f"?safe={safe_contract.address}", format="json"
        )
        self.assertCountEqual(response.data["results"], expected)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.get(url + f"?delegator={delegator}", format="json")
        self.assertCountEqual(response.data["results"], expected)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected = [
            {
                "delegate": safe_contract_delegate_1.delegate,
                "delegator": safe_contract_delegate_1.delegator,
                "label": safe_contract_delegate_1.label,
                "safe": safe_contract.address,
            },
            {
                "delegate": safe_contract_delegate_3.delegate,
                "delegator": safe_contract_delegate_3.delegator,
                "label": safe_contract_delegate_3.label,
                "safe": safe_contract_delegate_3.safe_contract_id,
            },
        ]
        response = self.client.get(
            url + f"?delegate={safe_contract_delegate_1.delegate}", format="json"
        )
        self.assertCountEqual(response.data["results"], expected)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test not found delegate address
        response = self.client.get(
            url + f"?delegate={Account.create().address}", format="json"
        )
        self.assertCountEqual(response.data["results"], [])
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delegate_delete(self):
        url_name = "v2:history:delegate"
        safe_address = Account.create().address
        delegate = Account.create()
        delegator = Account.create()
        chain_id = self.ethereum_client.get_chain_id()
        hash_to_sign = DelegateSignatureHelperV2.calculate_hash(
            delegate.address, chain_id, False
        )
        # Test delete using delegate signature and then delegator signature
        for signer in (delegate, delegator):
            with self.subTest(signer=signer):
                SafeContractDelegateFactory(
                    delegate=delegate.address, delegator=delegator.address
                )  # Expected to be deleted
                SafeContractDelegateFactory(
                    safe_contract=None,
                    delegate=delegate.address,
                    delegator=delegator.address,
                )  # Expected to be deleted
                SafeContractDelegateFactory(
                    delegate=delegate.address,  # random delegator, should not be deleted
                )
                self.assertEqual(SafeContractDelegate.objects.count(), 3)

                data = {
                    "signature": signer.signHash(hash_to_sign)["signature"].hex(),
                    "delegator": delegator.address,
                }
                response = self.client.delete(
                    reverse(url_name, args=(delegate.address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
                self.assertEqual(SafeContractDelegate.objects.count(), 1)
                response = self.client.delete(
                    reverse(url_name, args=(delegate.address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
                SafeContractDelegate.objects.all().delete()

        # Try to delete delegate for a specific safe
        with mock.patch(
            "safe_transaction_service.history.serializers.get_safe_owners",
            return_value=[Account.create().address],
        ) as get_safe_owners_mock:
            SafeContractDelegateFactory(
                delegate=delegate.address, delegator=delegator.address
            )  # Should not be deleted
            SafeContractDelegateFactory(
                safe_contract__address=safe_address,
                delegate=delegate.address,
                delegator=delegator.address,
            )  # Expected to be deleted
            self.assertEqual(SafeContractDelegate.objects.count(), 2)
            data = {
                "safe": safe_address,
                "signature": delegator.signHash(hash_to_sign)["signature"].hex(),
                "delegator": delegator.address,
            }
            response = self.client.delete(
                reverse(url_name, args=(delegate.address,)),
                format="json",
                data=data,
            )
            self.assertIn(
                f"Provided delegator={delegator.address} is not an owner of Safe={safe_address}",
                response.data["non_field_errors"][0],
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(SafeContractDelegate.objects.count(), 2)
            # Mock safe owners
            get_safe_owners_mock.return_value = [delegator.address]
            data = {
                "safe": safe_address,
                "signature": delegator.signHash(hash_to_sign)["signature"].hex(),
                "delegator": delegator.address,
            }
            response = self.client.delete(
                reverse(url_name, args=(delegate.address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            self.assertEqual(SafeContractDelegate.objects.count(), 1)

        # Try an invalid signer
        signer = Account.create()
        data = {
            "signature": signer.signHash(hash_to_sign)["signature"].hex(),
            "delegator": delegator.address,
        }
        response = self.client.delete(
            reverse(url_name, args=(delegate.address,)), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "Signature does not match provided delegate",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        data = {
            "signature": delegator.signHash(hash_to_sign)["signature"].hex(),
            "delegator": delegator.address,
        }
        response = self.client.delete(
            reverse(url_name, args=(delegate.address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(SafeContractDelegate.objects.count(), 0)

        # Try an invalid delegate_address
        response = self.client.delete(
            reverse(
                url_name, args=("0x00000000000000000000000000000000000000000000000",)
            ),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            "Checksum address validation failed",
            response.data["message"],
        )

        # Try an invalid signature
        with mock.patch(
            "gnosis.safe.safe_signature.SafeSignature.parse_signature",
            return_value=[],
        ) as parse_signature_mock:
            # No signatures
            response = self.client.delete(
                reverse(url_name, args=(delegate.address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn(
                "Signature is not valid",
                response.data["non_field_errors"][0],
            )

            # More than 1 signature
            parse_signature_mock.return_value = [None, None]
            response = self.client.delete(
                reverse(url_name, args=(delegate.address,)),
                format="json",
                data=data,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn(
                "More than one signatures detected, just one is expected",
                response.data["non_field_errors"][0],
            )
