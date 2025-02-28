import datetime
import json
from unittest import mock
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

import eth_abi
from eth_account import Account
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.utils import fast_is_checksum_address, fast_keccak_text
from safe_eth.safe.enums import SafeOperationEnum
from safe_eth.safe.safe import Safe
from safe_eth.safe.safe_signature import SafeSignature, SafeSignatureType
from safe_eth.safe.signatures import signature_to_bytes
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin
from safe_eth.util.util import to_0x_hex_str

from ...contracts.models import ContractQuerySet
from ...contracts.tests.factories import ContractFactory
from ...contracts.tx_decoder import DbTxDecoder
from ...tokens.models import Token
from ...tokens.tests.factories import TokenFactory
from ...utils.utils import datetime_to_str
from ..helpers import DelegateSignatureHelperV2, DeleteMultisigTxSignatureHelper
from ..models import MultisigConfirmation, MultisigTransaction, SafeContractDelegate
from ..serializers import TransferType
from ..views_v2 import SafeMultisigTransactionListView
from .factories import (
    ERC20TransferFactory,
    ERC721TransferFactory,
    EthereumTxFactory,
    InternalTxFactory,
    ModuleTransactionFactory,
    MultisigConfirmationFactory,
    MultisigTransactionFactory,
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
            "expiry_date": datetime_to_str(
                timezone.now() + datetime.timedelta(minutes=30)
            ),
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
            data["signature"] = to_0x_hex_str(
                delegator.unsafe_sign_hash(hash_to_sign)["signature"]
            )
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

            # Create expired delegate
            data["expiry_date"] = datetime_to_str(
                timezone.now() - datetime.timedelta(hours=1)
            )
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            # Remove expiry date
            data["expiry_date"] = None
            response = self.client.post(url, format="json", data=data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(SafeContractDelegate.objects.count(), 1)
            safe_contract_delegate = SafeContractDelegate.objects.get()
            self.assertIsNone(safe_contract_delegate.expiry_date)

        # Create delegate without a Safe
        hash_to_sign = DelegateSignatureHelperV2.calculate_hash(
            delegate.address, chain_id, False
        )
        data = {
            "label": "Kim Wexler",
            "delegate": delegate.address,
            "delegator": delegator.address,
            "signature": to_0x_hex_str(
                delegator.unsafe_sign_hash(hash_to_sign)["signature"]
            ),
        }
        response = self.client.post(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 2)

        # Test bad request with an invalid signature
        signature = signature_to_bytes(0, int(delegator.address, 16), 65) + HexBytes(
            "0" * 65
        )
        data["signature"] = to_0x_hex_str(signature)
        response = self.client.post(url, format="json", data=data)
        self.assertIn(
            f"Signature of type=CONTRACT_SIGNATURE for signer={delegator.address} is not valid",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delegate_creation_without_chain_id(self):
        chain_id = None
        delegate = Account.create()
        delegator = Account.create()
        hash_to_sign = DelegateSignatureHelperV2.calculate_hash(
            delegate.address, chain_id, False
        )
        data = {
            "label": "Kim Wexler",
            "delegate": delegate.address,
            "delegator": delegator.address,
            "signature": to_0x_hex_str(
                delegator.unsafe_sign_hash(hash_to_sign)["signature"]
            ),
        }

        response = self.client.post(
            reverse("v2:history:delegates"), format="json", data=data
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)

    def test_delegate_creation_without_chain_id_with_safe(self):
        safe = SafeContractFactory()
        chain_id = None
        delegate = Account.create()
        delegator = Account.create()
        hash_to_sign = DelegateSignatureHelperV2.calculate_hash(
            delegate.address, chain_id, False
        )
        data = {
            "label": "Kim Wexler",
            "safe": safe.address,
            "delegate": delegate.address,
            "delegator": delegator.address,
            "signature": to_0x_hex_str(
                delegator.unsafe_sign_hash(hash_to_sign)["signature"]
            ),
        }

        with mock.patch(
            "safe_transaction_service.history.serializers.get_safe_owners",
            return_value=[delegator.address],
        ):
            response = self.client.post(
                reverse("v2:history:delegates"), format="json", data=data
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeContractDelegate.objects.count(), 1)
        safe_contract_delegate = SafeContractDelegate.objects.get()
        self.assertEqual(safe_contract_delegate.delegate, delegate.address)
        self.assertEqual(safe_contract_delegate.delegator, delegator.address)
        self.assertEqual(safe_contract_delegate.safe_contract_id, safe.address)

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
                "expiry_date": datetime_to_str(safe_contract_delegate_1.expiry_date),
            },
            {
                "delegate": safe_contract_delegate_2.delegate,
                "delegator": safe_contract_delegate_2.delegator,
                "label": safe_contract_delegate_2.label,
                "safe": safe_contract.address,
                "expiry_date": datetime_to_str(safe_contract_delegate_2.expiry_date),
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
                "expiry_date": datetime_to_str(safe_contract_delegate_1.expiry_date),
            },
            {
                "delegate": safe_contract_delegate_3.delegate,
                "delegator": safe_contract_delegate_3.delegator,
                "label": safe_contract_delegate_3.label,
                "safe": safe_contract_delegate_3.safe_contract_id,
                "expiry_date": datetime_to_str(safe_contract_delegate_3.expiry_date),
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
                    "signature": to_0x_hex_str(
                        signer.unsafe_sign_hash(hash_to_sign)["signature"]
                    ),
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
                "signature": to_0x_hex_str(
                    delegator.unsafe_sign_hash(hash_to_sign)["signature"]
                ),
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
                "signature": to_0x_hex_str(
                    delegator.unsafe_sign_hash(hash_to_sign)["signature"]
                ),
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
            "signature": to_0x_hex_str(
                signer.unsafe_sign_hash(hash_to_sign)["signature"]
            ),
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
            "signature": to_0x_hex_str(
                delegator.unsafe_sign_hash(hash_to_sign)["signature"]
            ),
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
            "safe_eth.safe.safe_signature.SafeSignature.parse_signature",
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

    def test_safe_balances_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["count"], 1)
        self.assertEqual(len(response_json["results"]), 1)
        self.assertIsNone(response_json["results"][0]["tokenAddress"])
        self.assertEqual(response_json["results"][0]["balance"], str(value))

        tokens_value = 12
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,)), format="json"
        )
        response_json = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response_json["count"], 1)
        self.assertEqual(len(response_json["results"]), 1)

        self.assertEqual(Token.objects.count(), 0)
        ERC20TransferFactory(address=erc20.address, to=safe_address)
        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,)), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Token.objects.count(), 1)
        response_json = response.json()
        self.assertEqual(response_json["count"], 2)
        self.assertCountEqual(
            response_json["results"],
            [
                {"tokenAddress": None, "balance": str(value), "token": None},
                {
                    "tokenAddress": erc20.address,
                    "balance": str(tokens_value),
                    "token": {
                        "name": erc20.functions.name().call(),
                        "symbol": erc20.functions.symbol().call(),
                        "decimals": erc20.functions.decimals().call(),
                        "logoUri": Token.objects.first().get_full_logo_uri(),
                    },
                },
            ],
        )

        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,)) + "?trusted=True",
            format="json",
        )
        response_json = response.json()
        self.assertCountEqual(
            response_json["results"],
            [{"tokenAddress": None, "balance": str(value), "token": None}],
        )
        Token.objects.all().update(trusted=True)

        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,)) + "?trusted=True",
            format="json",
        )
        response_json = response.json()
        self.assertCountEqual(
            response_json["results"],
            [
                {"tokenAddress": None, "balance": str(value), "token": None},
                {
                    "tokenAddress": erc20.address,
                    "balance": str(tokens_value),
                    "token": {
                        "name": erc20.functions.name().call(),
                        "symbol": erc20.functions.symbol().call(),
                        "decimals": erc20.functions.decimals().call(),
                        "logoUri": Token.objects.first().get_full_logo_uri(),
                    },
                },
            ],
        )

    def test_safe_pagination_balances_view(self):
        safe_address = Account.create().address
        self.send_ether(safe_address, 7)
        SafeContractFactory(address=safe_address)
        value = 7

        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,))
            + "?limit=1&offset=0",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["count"], 1)
        self.assertIsNone(response_json["next"])
        self.assertIsNone(response_json["previous"])
        self.assertEqual(len(response_json["results"]), 1)
        self.assertIsNone(response_json["results"][0]["tokenAddress"])
        self.assertEqual(response_json["results"][0]["balance"], str(value))

        # Next page should return empty results
        response = self.client.get(
            reverse("v2:history:safe-balances", args=(safe_address,))
            + "?limit=1&offset=1",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["count"], 1)
        self.assertEqual(len(response_json["results"]), 0)

        tokens_value = 12
        # Deploy UXI token
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        ERC20TransferFactory(address=erc20.address, to=safe_address)
        # Deploy another token
        flipe_amount = 100
        other_erc20 = self.deploy_erc20(
            name="Flipe", symbol="FLP", owner=safe_address, amount=flipe_amount
        )
        ERC20TransferFactory(address=other_erc20.address, to=safe_address)

        with mock.patch(
            "safe_transaction_service.history.services.balance_service.BalanceService._filter_tokens",
            return_value=[erc20.address, other_erc20.address],
        ):
            response = self.client.get(
                reverse("v2:history:safe-balances", args=(safe_address,))
                + "?limit=1&offset=0",
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(response_json["count"], 3)
            self.assertIsNotNone(response_json["next"])
            self.assertIsNone(response_json["previous"])
            self.assertEqual(len(response_json["results"]), 1)
            self.assertIsNone(response_json["results"][0]["tokenAddress"])
            self.assertEqual(response_json["results"][0]["balance"], str(value))

            response = self.client.get(
                reverse("v2:history:safe-balances", args=(safe_address,))
                + "?limit=1&offset=1",
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(response_json["count"], 3)
            self.assertIsNotNone(response_json["next"])
            self.assertIsNotNone(response_json["previous"])
            self.assertEqual(len(response_json["results"]), 1)
            self.assertCountEqual(
                response_json["results"],
                [
                    {
                        "tokenAddress": erc20.address,
                        "balance": str(tokens_value),
                        "token": {
                            "name": erc20.functions.name().call(),
                            "symbol": erc20.functions.symbol().call(),
                            "decimals": erc20.functions.decimals().call(),
                            "logoUri": Token.objects.get(
                                address=erc20.address
                            ).get_full_logo_uri(),
                        },
                    },
                ],
            )

            response = self.client.get(
                reverse("v2:history:safe-balances", args=(safe_address,))
                + "?limit=1&offset=2",
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_json = response.json()
            self.assertEqual(response_json["count"], 3)
            self.assertIsNone(response_json["next"])
            self.assertIsNotNone(response_json["previous"])
            self.assertEqual(len(response_json["results"]), 1)
            self.assertCountEqual(
                response_json["results"],
                [
                    {
                        "tokenAddress": other_erc20.address,
                        "balance": str(flipe_amount),
                        "token": {
                            "name": other_erc20.functions.name().call(),
                            "symbol": other_erc20.functions.symbol().call(),
                            "decimals": other_erc20.functions.decimals().call(),
                            "logoUri": Token.objects.get(
                                address=other_erc20.address
                            ).get_full_logo_uri(),
                        },
                    },
                ],
            )

    def test_get_multisig_transactions(self):
        safe = self.deploy_test_safe()
        safe_address = safe.address
        proposer = safe.retrieve_owners()[0]
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["count_unique_nonce"], 0)

        multisig_tx = MultisigTransactionFactory(
            safe=safe_address, proposer=proposer, trusted=True
        )
        # Not trusted multisig transaction should not be returned by default
        MultisigTransactionFactory(safe=safe_address, proposer=proposer, trusted=False)
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["count_unique_nonce"], 1)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 0)
        self.assertIsInstance(response.data["results"][0]["nonce"], str)
        self.assertTrue(
            fast_is_checksum_address(response.data["results"][0]["executor"])
        )
        self.assertEqual(
            response.data["results"][0]["transaction_hash"],
            multisig_tx.ethereum_tx.tx_hash,
        )
        # Test camelCase
        self.assertEqual(
            response.json()["results"][0]["transactionHash"],
            multisig_tx.ethereum_tx.tx_hash,
        )
        # Check Etag header
        self.assertTrue(response["Etag"])
        MultisigConfirmationFactory(multisig_transaction=multisig_tx)
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 1)
        self.assertEqual(response.data["results"][0]["proposer"], proposer)
        self.assertIsNone(response.data["results"][0]["proposed_by_delegate"])

        # Check proposed_by_delegate
        delegate = Account.create().address
        multisig_tx.proposed_by_delegate = delegate
        multisig_tx.save()
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["proposer"], proposer)
        self.assertEqual(response.data["results"][0]["proposed_by_delegate"], delegate)

        # Check not trusted
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?trusted=False",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)

        MultisigTransactionFactory(
            safe=safe_address, nonce=multisig_tx.nonce, trusted=True
        )
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["count_unique_nonce"], 1)

        #
        # Mock get_queryset with empty queryset return value to get proper error in case of fail
        with mock.patch.object(
            SafeMultisigTransactionListView,
            "get_queryset",
            return_value=MultisigTransaction.objects.none(),
        ) as patched_queryset:
            response = self.client.get(
                reverse("v2:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            # view shouldn't be called
            patched_queryset.assert_not_called()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 2)
            self.assertEqual(response.data["count_unique_nonce"], 1)

    def test_get_multisig_transactions_unique_nonce(self):
        """
        Unique nonce should follow the trusted filter
        """

        safe = self.deploy_test_safe()
        safe_address = safe.address
        url = reverse("v2:history:multisig-transactions", args=(safe_address,))
        response = self.client.get(
            url,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["count_unique_nonce"], 0)

        MultisigTransactionFactory(safe=safe_address, nonce=6, trusted=True)
        MultisigTransactionFactory(safe=safe_address, nonce=12, trusted=False)

        # Unique nonce ignores not trusted transactions by default
        response = self.client.get(
            url,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["count_unique_nonce"], 1)

        response = self.client.get(
            url + "?trusted=False",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["count_unique_nonce"], 2)

    @mock.patch.object(
        DbTxDecoder, "get_data_decoded", return_value={"param1": "value"}
    )
    def test_get_multisig_transactions_not_decoded(
        self, get_data_decoded_mock: MagicMock
    ):
        try:
            safe = self.deploy_test_safe()
            safe_address = safe.address
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            multisig_transaction = MultisigTransactionFactory(
                safe=safe_address,
                operation=SafeOperationEnum.CALL.value,
                data=b"abcd",
                trusted=True,
            )
            safe_address = multisig_transaction.safe
            response = self.client.get(
                reverse("v2:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data["results"][0]["data_decoded"], {"param1": "value"}
            )

            multisig_transaction.operation = SafeOperationEnum.DELEGATE_CALL.value
            multisig_transaction.save()
            response = self.client.get(
                reverse("v2:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIsNone(response.data["results"][0]["data_decoded"])

            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            ContractFactory(
                address=multisig_transaction.to, trusted_for_delegate_call=True
            )
            # Force don't use cache because we are not cleaning the cache on contracts change
            with mock.patch(
                "safe_transaction_service.history.views.settings.CACHE_VIEW_DEFAULT_TIMEOUT",
                0,
            ):
                response = self.client.get(
                    reverse("v2:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(
                    response.data["results"][0]["data_decoded"], {"param1": "value"}
                )
        finally:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()

    def test_get_multisig_transactions_filters(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        multisig_transaction = MultisigTransactionFactory(
            safe=safe_address,
            nonce=0,
            ethereum_tx=None,
            trusted=True,
            enable_safe_tx_hash_calculation=True,
        )
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?nonce=0",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?to=0x2a",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["to"][0], "Enter a valid checksummed Ethereum Address."
        )

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + f"?to={multisig_transaction.to}",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?nonce=1",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?executed=true",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?executed=false",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?has_confirmations=True",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

        MultisigConfirmationFactory(
            multisig_transaction=multisig_transaction,
            force_sign_with_account=safe_owner_1,
        )
        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,))
            + "?has_confirmations=True",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_get_multisig_transaction(self):
        safe = self.deploy_test_safe()
        safe_address = safe.address
        safe_tx_hash = to_0x_hex_str(fast_keccak_text("gnosis"))
        response = self.client.get(
            reverse("v2:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        add_owner_with_threshold_data = HexBytes(
            "0x0d582f130000000000000000000000001b9a0da11a5cace4e7035993cbb2e4"
            "b1b3b164cf000000000000000000000000000000000000000000000000000000"
            "0000000001"
        )

        multisig_tx = MultisigTransactionFactory(
            safe=safe_address, data=add_owner_with_threshold_data
        )
        safe_tx_hash = multisig_tx.safe_tx_hash
        response = self.client.get(
            reverse("v2:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["confirmations"]), 0)
        self.assertTrue(fast_is_checksum_address(response.data["executor"]))
        self.assertEqual(
            response.data["transaction_hash"], multisig_tx.ethereum_tx.tx_hash
        )
        self.assertEqual(response.data["origin"], multisig_tx.origin)
        self.assertFalse(response.data["trusted"])
        self.assertIsNone(response.data["max_fee_per_gas"])
        self.assertIsNone(response.data["max_priority_fee_per_gas"])
        self.assertIsNone(response.data["proposer"])
        self.assertIsNone(response.data["proposed_by_delegate"])
        self.assertIsInstance(response.data["nonce"], str)
        self.assertEqual(
            response.data["data_decoded"],
            {
                "method": "addOwnerWithThreshold",
                "parameters": [
                    {
                        "name": "owner",
                        "type": "address",
                        "value": "0x1b9a0DA11a5caCE4e703599" "3Cbb2E4B1B3b164Cf",
                    },
                    {"name": "_threshold", "type": "uint256", "value": "1"},
                ],
            },
        )

        # Test camelCase
        self.assertEqual(
            response.json()["transactionHash"], multisig_tx.ethereum_tx.tx_hash
        )
        # Test empty origin object
        multisig_tx.origin = {}
        multisig_tx.save(update_fields=["origin"])
        response = self.client.get(
            reverse("v2:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["origin"], json.dumps({}))
        self.assertEqual(json.loads(response.data["origin"]), {})

        # Test origin object
        origin = {"app": "Testing App", "name": "Testing"}
        multisig_tx.origin = origin
        multisig_tx.save(update_fields=["origin"])
        response = self.client.get(
            reverse("v2:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["origin"], json.dumps(origin))
        self.assertEqual(json.loads(response.data["origin"]), origin)

        # Test proposer
        proposer = Account.create().address
        multisig_tx.proposer = proposer
        multisig_tx.save()
        response = self.client.get(
            reverse("v2:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.data["proposer"], proposer)

        # Check proposed_by_delegate
        delegate = Account.create().address
        multisig_tx.proposed_by_delegate = delegate
        multisig_tx.save()
        response = self.client.get(
            reverse("v2:history:multisig-transaction", args=(safe_tx_hash,)),
            format="json",
        )
        self.assertEqual(response.data["proposer"], proposer)
        self.assertEqual(response.data["proposed_by_delegate"], delegate)

    def test_post_multisig_transactions_null_signature(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address
        safe = Safe(safe_address, self.ethereum_client)

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
            "signature": None,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(
            reverse(
                "v2:history:multisig-transaction",
                args=(data["contractTransactionHash"],),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["executor"])
        self.assertEqual(len(response.data["confirmations"]), 0)

    def test_post_multisig_transactions(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        response = self.client.get(
            reverse(
                "v2:history:multisig-transaction",
                args=(data["contractTransactionHash"],),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["executor"])
        self.assertEqual(len(response.data["confirmations"]), 0)
        self.assertEqual(response.data["proposer"], data["sender"])
        self.assertIsNone(response.data["proposed_by_delegate"])

        # Test confirmation with signature
        data["signature"] = to_0x_hex_str(
            safe_owner_1.unsafe_sign_hash(safe_tx.safe_tx_hash)["signature"]
        )
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        modified = multisig_transaction_db.modified
        multisig_transaction_db.refresh_from_db()
        self.assertTrue(multisig_transaction_db.trusted)  # Now it should be trusted
        self.assertGreater(
            multisig_transaction_db.modified, modified
        )  # Modified should be updated

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(len(response.data["results"][0]["confirmations"]), 1)
        self.assertEqual(
            response.data["results"][0]["confirmations"][0]["signature"],
            data["signature"],
        )
        self.assertTrue(response.data["results"][0]["trusted"])

        # Sign with a different user that sender
        random_user_account = Account.create()
        data["signature"] = to_0x_hex_str(
            random_user_account.unsafe_sign_hash(safe_tx.safe_tx_hash)["signature"]
        )
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Signer={random_user_account.address} is not an owner",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Use random user as sender (not owner)
        del data["signature"]
        data["sender"] = random_user_account.address
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertIn(
            f"Sender={random_user_account.address} is not an owner",
            response.data["non_field_errors"][0],
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_post_multisig_transaction_with_zero_to(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        data = {
            "to": NULL_ADDRESS,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

    def test_post_multisig_transaction_with_1271_signature(self):
        account = Account.create()
        safe_owner = self.deploy_test_safe(owners=[account.address])
        safe = self.deploy_test_safe(owners=[safe_owner.address])

        data = {
            "to": account.address,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            "sender": safe_owner.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        safe_tx_hash_preimage = safe_tx.safe_tx_hash_preimage

        safe_owner_message_hash = safe_owner.get_message_hash(safe_tx_hash_preimage)
        safe_owner_signature = account.unsafe_sign_hash(safe_owner_message_hash)[
            "signature"
        ]
        signature_1271 = (
            signature_to_bytes(
                0, int.from_bytes(HexBytes(safe_owner.address), byteorder="big"), 65
            )
            + eth_abi.encode(["bytes"], [safe_owner_signature])[32:]
        )

        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(signature_1271)

        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe.address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx_hash
        )
        self.assertTrue(multisig_transaction_db.trusted)
        self.assertEqual(MultisigConfirmation.objects.count(), 1)

        # Test MultisigConfirmation endpoint
        confirmation_data = {"signature": data["signature"]}
        MultisigConfirmation.objects.all().delete()
        response = self.client.post(
            reverse(
                "v1:history:multisig-transaction-confirmations",
                args=(to_0x_hex_str(safe_tx_hash),),
            ),
            format="json",
            data=confirmation_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigConfirmation.objects.count(), 1)

    def test_post_multisig_transaction_with_trusted_user(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address
        data = {
            "to": Account.create().address,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)

        factory = APIRequestFactory()
        request = factory.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        response = SafeMultisigTransactionListView.as_view()(request, safe_address)
        response.render()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        # Create user
        user = get_user_model().objects.create(
            username="batman", password="very-private"
        )
        request = factory.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        force_authenticate(request, user=user)
        response = SafeMultisigTransactionListView.as_view()(request, safe_address)
        response.render()
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertFalse(multisig_transaction_db.trusted)

        # Assign permissions to user
        permission = Permission.objects.get(codename="create_trusted")
        user.user_permissions.add(permission)
        request = factory.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        user = get_user_model().objects.get()  # Flush permissions cache
        force_authenticate(request, user=user)
        response = SafeMultisigTransactionListView.as_view()(request, safe_address)
        response.render()
        multisig_transaction_db = MultisigTransaction.objects.first()
        self.assertTrue(multisig_transaction_db.trusted)

    def test_post_multisig_transaction_executed(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
        }
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        multisig_transaction = MultisigTransaction.objects.first()
        multisig_transaction.ethereum_tx = EthereumTxFactory()
        multisig_transaction.save(update_fields=["ethereum_tx"])
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f'Tx with safe-tx-hash={data["contractTransactionHash"]} '
            f"for safe={safe.address} was already executed in "
            f"tx-hash={multisig_transaction.ethereum_tx_id}",
            response.data["non_field_errors"],
        )

        # Check another tx with same nonce
        data["to"] = Account.create().address
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f"Tx with nonce={safe_tx.safe_nonce} for safe={safe.address} "
            f"already executed in tx-hash={multisig_transaction.ethereum_tx_id}",
            response.data["non_field_errors"],
        )

        # Successfully insert tx with nonce=1
        data["nonce"] = 1
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_post_multisig_transactions_with_origin(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        origin_max_len = 200  # Origin field limit
        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owner_1.address,
            "origin": "A" * (origin_max_len + 1),
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        data["origin"] = "A" * origin_max_len
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx.safe_tx_hash
        )
        self.assertEqual(multisig_tx_db.origin, data["origin"])
        data["origin"] = '{"url": "test", "name":"test"}'
        data["nonce"] = 1
        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx.safe_tx_hash
        )
        self.assertEqual(multisig_tx_db.origin, json.loads(data["origin"]))

    def test_post_multisig_transactions_with_multiple_signatures(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe.address

        response = self.client.get(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owners[0].address,
            "origin": "Testing origin field",
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(
            b"".join(
                [
                    safe_owner.unsafe_sign_hash(safe_tx_hash)["signature"]
                    for safe_owner in safe_owners
                ]
            )
        )
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        multisig_tx_db = MultisigTransaction.objects.get(
            safe_tx_hash=safe_tx.safe_tx_hash
        )
        self.assertEqual(multisig_tx_db.origin, data["origin"])

        multisig_confirmations = MultisigConfirmation.objects.filter(
            multisig_transaction_hash=safe_tx_hash
        )
        self.assertEqual(len(multisig_confirmations), len(safe_owners))
        for multisig_confirmation in multisig_confirmations:
            safe_signatures = SafeSignature.parse_signature(
                multisig_confirmation.signature, safe_tx_hash
            )
            self.assertEqual(len(safe_signatures), 1)
            safe_signature = safe_signatures[0]
            self.assertEqual(safe_signature.signature_type, SafeSignatureType.EOA)
            self.assertIn(safe_signature.owner, safe_owner_addresses)
            safe_owner_addresses.remove(safe_signature.owner)

    def test_post_multisig_transactions_with_delegate(self):
        safe_owners = [Account.create() for _ in range(4)]
        safe_owner_addresses = [s.address for s in safe_owners]
        safe_delegate = Account.create()
        safe = self.deploy_test_safe(owners=safe_owner_addresses, threshold=3)
        safe_address = safe.address

        self.assertEqual(MultisigTransaction.objects.count(), 0)

        to = Account.create().address
        data = {
            "to": to,
            "value": 100000000000000000,
            "data": None,
            "operation": 0,
            "nonce": 0,
            "safeTxGas": 0,
            "baseGas": 0,
            "gasPrice": 0,
            "gasToken": "0x0000000000000000000000000000000000000000",
            "refundReceiver": "0x0000000000000000000000000000000000000000",
            # "contractTransactionHash": "0x1c2c77b29086701ccdda7836c399112a9b715c6a153f6c8f75c84da4297f60d3",
            "sender": safe_owners[0].address,
            "origin": "Testing origin field",
        }

        safe_tx = safe.build_multisig_tx(
            data["to"],
            data["value"],
            data["data"],
            data["operation"],
            data["safeTxGas"],
            data["baseGas"],
            data["gasPrice"],
            data["gasToken"],
            data["refundReceiver"],
            safe_nonce=data["nonce"],
        )
        safe_tx_hash = safe_tx.safe_tx_hash
        data["contractTransactionHash"] = to_0x_hex_str(safe_tx_hash)
        data["signature"] = to_0x_hex_str(
            safe_delegate.unsafe_sign_hash(safe_tx_hash)["signature"]
        )

        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f"Signer={safe_delegate.address} is not an owner or delegate",
            response.data["non_field_errors"][0],
        )

        data["sender"] = safe_delegate.address
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            f"Sender={safe_delegate.address} is not an owner or delegate",
            response.data["non_field_errors"][0],
        )

        # Add delegates (to check there's no issue with delegating twice to the same account)
        safe_contract_delegate = SafeContractDelegateFactory(
            safe_contract__address=safe_address,
            delegate=safe_delegate.address,
            delegator=safe_owners[0].address,
        )
        SafeContractDelegateFactory(
            safe_contract=safe_contract_delegate.safe_contract,
            delegate=safe_delegate.address,
            delegator=safe_owners[1].address,
        )
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MultisigTransaction.objects.count(), 1)
        self.assertEqual(MultisigConfirmation.objects.count(), 0)
        multisig_transaction = MultisigTransaction.objects.first()
        self.assertTrue(multisig_transaction.trusted)
        # Proposer should be the owner address not the delegate
        self.assertNotEqual(multisig_transaction.proposer, safe_delegate.address)
        self.assertEqual(multisig_transaction.proposer, safe_owners[0].address)
        self.assertEqual(
            multisig_transaction.proposed_by_delegate, safe_delegate.address
        )

        data["signature"] = data["signature"] + data["signature"][2:]
        response = self.client.post(
            reverse("v2:history:multisig-transactions", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(
            "Just one signature is expected if using delegates",
            response.data["non_field_errors"][0],
        )

    def test_post_multisig_transaction_with_delegate_call(self):
        safe_owner_1 = Account.create()
        safe = self.deploy_test_safe(owners=[safe_owner_1.address])
        safe_address = safe.address

        try:
            response = self.client.get(
                reverse("v2:history:multisig-transactions", args=(safe_address,)),
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["count"], 0)

            data = {
                "to": Account.create().address,
                "value": 0,
                "data": "0x12121212",
                "operation": SafeOperationEnum.DELEGATE_CALL.value,
                "nonce": 0,
                "safeTxGas": 0,
                "baseGas": 0,
                "gasPrice": 0,
                "gasToken": "0x0000000000000000000000000000000000000000",
                "refundReceiver": "0x0000000000000000000000000000000000000000",
                "sender": safe_owner_1.address,
            }
            safe_tx = safe.build_multisig_tx(
                data["to"],
                data["value"],
                data["data"],
                data["operation"],
                data["safeTxGas"],
                data["baseGas"],
                data["gasPrice"],
                data["gasToken"],
                data["refundReceiver"],
                safe_nonce=data["nonce"],
            )
            data["contractTransactionHash"] = to_0x_hex_str(safe_tx.safe_tx_hash)

            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            # Disable creation with delegate call and not trusted contract
            with self.settings(
                DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION=True
            ):
                response = self.client.post(
                    reverse("v2:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(
                    response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY
                )

            # Enable creation with delegate call
            with self.settings(
                DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION=False
            ):
                response = self.client.post(
                    reverse("v2:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                multisig_transaction_db = MultisigTransaction.objects.first()
                self.assertEqual(multisig_transaction_db.operation, 1)

            # Disable creation with delegate call and trusted contract
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()
            ContractFactory(address=data["to"], trusted_for_delegate_call=True)
            with self.settings(
                DISABLE_CREATION_MULTISIG_TRANSACTIONS_WITH_DELEGATE_CALL_OPERATION=True
            ):
                response = self.client.post(
                    reverse("v2:history:multisig-transactions", args=(safe_address,)),
                    format="json",
                    data=data,
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        finally:
            ContractQuerySet.cache_trusted_addresses_for_delegate_call.clear()

    def test_delete_multisig_transaction(self):
        owner_account = Account.create()
        safe_tx_hash = to_0x_hex_str(fast_keccak_text("random-tx"))
        url = reverse("v2:history:multisig-transaction", args=(safe_tx_hash,))
        data = {"signature": "0x" + "1" * (130 * 2)}  # 2 signatures of 65 bytes
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Add our test MultisigTransaction to the database
        safe = SafeContractFactory()
        multisig_transaction = MultisigTransactionFactory(
            safe_tx_hash=safe_tx_hash, safe=safe.address
        )

        # Add other MultisigTransactions to the database to make sure they are not deleted
        MultisigTransactionFactory()
        MultisigTransactionFactory()

        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Executed transactions cannot be deleted", code="invalid"
                    )
                ]
            },
        )

        multisig_transaction.ethereum_tx = None
        multisig_transaction.save(update_fields=["ethereum_tx"])
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Old transactions without proposer cannot be deleted",
                        code="invalid",
                    )
                ]
            },
        )

        # Set a random proposer for the transaction
        multisig_transaction.proposer = Account.create().address
        multisig_transaction.save(update_fields=["proposer"])
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="1 owner signature was expected, 2 received",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a contract signature
        data = {"signature": "0x" + "0" * 130}  # 1 signature of 65 bytes
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Only EOA and ETH_SIGN signatures are supported",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a real not valid signature and set the right proposer
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.save(update_fields=["proposer"])
        data = {
            "signature": to_0x_hex_str(
                owner_account.unsafe_sign_hash(safe_tx_hash)["signature"]
            )  # Random signature
        }
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Provided signer is not the proposer or the delegate user who proposed the transaction",
                        code="invalid",
                    )
                ]
            },
        )

        # Calculate a valid message_hash
        message_hash = DeleteMultisigTxSignatureHelper.calculate_hash(
            safe.address,
            safe_tx_hash,
            self.ethereum_client.get_chain_id(),
            previous_totp=False,
        )

        # Use an expired user delegate
        safe_delegate = Account.create()
        safe_contract_delegate = SafeContractDelegateFactory(
            safe_contract_id=multisig_transaction.safe,
            delegate=safe_delegate.address,
            delegator=owner_account.address,
            expiry_date=timezone.now() - datetime.timedelta(minutes=1),
        )
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.proposed_by_delegate = safe_delegate.address
        multisig_transaction.save(update_fields=["proposer", "proposed_by_delegate"])
        data = {
            "signature": to_0x_hex_str(
                safe_delegate.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Provided signer is not the proposer or the delegate user who proposed the transaction",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a deleted user delegate
        safe_contract_delegate.delete()
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.proposed_by_delegate = safe_delegate.address
        multisig_transaction.save(update_fields=["proposer", "proposed_by_delegate"])
        data = {
            "signature": to_0x_hex_str(
                safe_delegate.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="Provided signer is not the proposer or the delegate user who proposed the transaction",
                        code="invalid",
                    )
                ]
            },
        )

        # Use a proper signature of an user delegate
        SafeContractDelegateFactory(
            safe_contract_id=multisig_transaction.safe,
            delegate=safe_delegate.address,
            delegator=owner_account.address,
        )
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.proposed_by_delegate = safe_delegate.address
        multisig_transaction.save(update_fields=["proposer", "proposed_by_delegate"])
        data = {
            "signature": to_0x_hex_str(
                safe_delegate.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        self.assertEqual(MultisigTransaction.objects.count(), 3)
        self.assertTrue(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(MultisigTransaction.objects.count(), 2)
        self.assertFalse(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )

        # Use a proper signature of a proposer user
        multisig_transaction = MultisigTransactionFactory(
            safe_tx_hash=safe_tx_hash, safe=safe.address, ethereum_tx=None
        )
        multisig_transaction.proposer = owner_account.address
        multisig_transaction.save(update_fields=["proposer"])
        data = {
            "signature": to_0x_hex_str(
                owner_account.unsafe_sign_hash(message_hash)["signature"]
            )
        }
        self.assertEqual(MultisigTransaction.objects.count(), 3)
        self.assertTrue(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(MultisigTransaction.objects.count(), 2)
        self.assertFalse(
            MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).exists()
        )

        # Trying to do the query again should raise a 404
        response = self.client.delete(url, format="json", data=data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_all_transactions_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

        # Factories create the models using current datetime, so as the txs are returned sorted they should be
        # in the reverse order that they were created
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        module_transaction = ModuleTransactionFactory(safe=safe_address)
        internal_tx_in = InternalTxFactory(to=safe_address, value=4)
        internal_tx_out = InternalTxFactory(
            _from=safe_address, value=5
        )  # Should not appear
        erc20_transfer_in = ERC20TransferFactory(to=safe_address)
        erc20_transfer_out = ERC20TransferFactory(_from=safe_address)
        another_multisig_transaction = MultisigTransactionFactory(safe=safe_address)
        another_safe_multisig_transaction = (
            MultisigTransactionFactory()
        )  # Should not appear, it's for another Safe

        # Should not appear as they are not executed
        for _ in range(2):
            MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)

        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)
        transfers_not_empty = [
            False,  # Multisig transaction, no transfer
            True,  # Erc transfer out
            True,  # Erc transfer in
            True,  # internal tx in
            False,  # Module transaction
            False,  # Multisig transaction
        ]
        for transfer_not_empty, transaction in zip(
            transfers_not_empty, response.data["results"]
        ):
            self.assertEqual(bool(transaction["transfers"]), transfer_not_empty)
            self.assertTrue(transaction["tx_type"])

        # Test pagination
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,)) + "?limit=3"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 3)
        self.assertIsInstance(response.data["results"][0]["nonce"], str)

        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?limit=4&offset=4"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 2)

        # Add transfer out for the module transaction and transfer in for the multisig transaction
        erc20_transfer_out = ERC20TransferFactory(
            _from=safe_address, ethereum_tx=module_transaction.internal_tx.ethereum_tx
        )
        # Add token info for that transfer
        token = TokenFactory(address=erc20_transfer_out.address)
        internal_tx_in = InternalTxFactory(
            to=safe_address, value=8, ethereum_tx=multisig_transaction.ethereum_tx
        )
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 6)
        self.assertEqual(len(response.data["results"]), 6)
        self.assertEqual(
            response.data["results"][4]["transfers"][0]["token_info"],
            {
                "type": "ERC20",
                "address": token.address,
                "name": token.name,
                "symbol": token.symbol,
                "decimals": token.decimals,
                "logo_uri": token.get_full_logo_uri(),
                "trusted": token.trusted,
            },
        )
        transfers_not_empty = [
            False,  # Multisig transaction, no transfer
            True,  # Erc transfer out
            True,  # Erc transfer in
            True,  # internal tx in
            True,  # Module transaction
            True,  # Multisig transaction
        ]
        for transfer_not_empty, transaction in zip(
            transfers_not_empty, response.data["results"]
        ):
            self.assertEqual(bool(transaction["transfers"]), transfer_not_empty)

    def test_all_transactions_executed(self):
        safe_address = Account.create().address

        # No mined
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        MultisigTransactionFactory(safe=safe_address, ethereum_tx=None)
        # Mined
        MultisigTransactionFactory(safe=safe_address)

        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_all_transactions_ordering(self):
        safe_address = Account.create().address

        # Older transaction
        erc20_transfer = ERC20TransferFactory(to=safe_address)
        # Newer transaction
        multisig_transaction = MultisigTransactionFactory(safe=safe_address)

        # Nonce is not allowed as a sorting parameter
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?ordering=nonce"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # By default, newer transactions first
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.data["results"][0]["transaction_hash"],
            multisig_transaction.ethereum_tx_id,
        )
        self.assertEqual(
            response.data["results"][1]["tx_hash"], erc20_transfer.ethereum_tx_id
        )
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?ordering=timestamp"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            response.data["results"][0]["tx_hash"], erc20_transfer.ethereum_tx_id
        )
        self.assertEqual(
            response.data["results"][1]["transaction_hash"],
            multisig_transaction.ethereum_tx_id,
        )

    def test_all_transactions_wrong_transfer_type_view(self):
        # No token in database, so we must trust the event
        safe_address = Account.create().address
        erc20_transfer_out = ERC20TransferFactory(
            _from=safe_address
        )  # ERC20 event (with `value`)
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC20_TRANSFER.name,
        )
        self.assertIsNone(response.data["results"][0]["transfers"][0]["token_id"])
        self.assertIsNotNone(response.data["results"][0]["transfers"][0]["value"])

        # Result should be the same, as we are adding an ERC20 token
        token = TokenFactory(address=erc20_transfer_out.address, decimals=18)
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC20_TRANSFER.name,
        )
        self.assertIsNone(response.data["results"][0]["transfers"][0]["token_id"])
        self.assertIsNotNone(response.data["results"][0]["transfers"][0]["value"])

        # Result should change if we set the token as an ERC721
        token.decimals = None
        token.save(update_fields=["decimals"])
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC721_TRANSFER.name,
        )
        # TokenId and Value must be swapped now
        self.assertIsNone(response.data["results"][0]["transfers"][0]["value"])
        self.assertIsNotNone(response.data["results"][0]["transfers"][0]["token_id"])

        # It should work with value=0
        safe_address = Account.create().address
        erc20_transfer_out = ERC20TransferFactory(
            _from=safe_address, value=0
        )  # ERC20 event (with `value`)
        token = TokenFactory(address=erc20_transfer_out.address, decimals=18)
        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
            + "?queued=False&trusted=True"
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["transfers"][0]["type"],
            TransferType.ERC20_TRANSFER.name,
        )
        self.assertIsNone(response.data["results"][0]["transfers"][0]["token_id"])
        self.assertEqual(response.data["results"][0]["transfers"][0]["value"], "0")

    def test_all_transactions_duplicated_multisig_tx_view(self):
        """
        Test 2 module transactions with the same tx_hash
        """
        safe_address = Account.create().address
        multisig_transaction_1 = MultisigTransactionFactory(safe=safe_address)
        multisig_transaction_2 = MultisigTransactionFactory(
            safe=safe_address,
            ethereum_tx=multisig_transaction_1.ethereum_tx,
        )

        self.assertEqual(
            multisig_transaction_1.ethereum_tx,
            multisig_transaction_2.ethereum_tx,
        )

        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        # We are aware of this. Pagination is done by `tx_hash`, so 2 transactions
        # with the same `tx_hash` will return a `count` of 1
        self.assertEqual(response.data["count"], 1)
        # Even if they have the same `tx_hash`, tx with higher nonce will come first
        self.assertEqual(
            [multisig_transaction_2.safe_tx_hash, multisig_transaction_1.safe_tx_hash],
            [multisig_tx["safe_tx_hash"] for multisig_tx in response.data["results"]],
        )

    def test_all_transactions_duplicated_module_view(self):
        """
        Test 2 module transactions with the same tx_hash
        """
        safe_address = Account.create().address
        module_transaction_1 = ModuleTransactionFactory(safe=safe_address)
        module_transaction_2 = ModuleTransactionFactory(
            safe=safe_address,
            internal_tx__ethereum_tx=module_transaction_1.internal_tx.ethereum_tx,
        )

        self.assertEqual(
            module_transaction_1.internal_tx.ethereum_tx,
            module_transaction_2.internal_tx.ethereum_tx,
        )

        response = self.client.get(
            reverse("v2:history:all-transactions", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        # We are aware of this. Pagination is done by `tx_hash`, so 2 transactions
        # with the same `tx_hash` will return a `count` of 1
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            {module_transaction_1.module, module_transaction_2.module},
            {module_tx["module"] for module_tx in response.data["results"]},
        )
