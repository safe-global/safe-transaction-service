# SPDX-License-Identifier: FSL-1.1-MIT
import datetime

from django.urls import reverse
from django.utils import timezone

from eth_abi import encode as encode_abi
from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.safe.enums import SafeOperationEnum
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.history.tests import factories as history_factories

from ..constants import COSIGNER_POLICY, ERC20_TRANSFER_POLICY
from ..models import FALLBACK_SELECTOR, PolicyRootStatus
from .factories import (
    ERC20_TRANSFER_SELECTOR,
    PolicyConfirmationFactory,
    PolicyContractFactory,
    PolicyRootInvalidationFactory,
    PolicyRootRequestFactory,
)


class TestSafePolicyConfirmationsView(APITestCase):
    def setUp(self):
        self.safe = Account.create().address
        self.url = reverse("v2:policies:policy-confirmations", args=(self.safe,))

    def test_invalid_address(self):
        response = self.client.get(
            reverse("v2:policies:policy-confirmations", args=("0x1234",))
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], 1)

    def test_not_checksummed_address(self):
        response = self.client.get(
            reverse("v2:policies:policy-confirmations", args=(self.safe.lower(),))
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_empty(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])

    def test_only_returns_the_requested_safe(self):
        PolicyConfirmationFactory(safe=self.safe)
        PolicyConfirmationFactory()

        response = self.client.get(self.url)

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["safe"], self.safe)

    def test_response(self):
        recipients = [Account.create().address for _ in range(2)]
        policy_contract = PolicyContractFactory(name=ERC20_TRANSFER_POLICY)
        confirmation = PolicyConfirmationFactory(
            safe=self.safe, policy=policy_contract.address, recipients=recipients
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["results"],
            [
                {
                    "safe": self.safe,
                    "guard": confirmation.guard,
                    "target": confirmation.target,
                    "selector": to_0x_hex_str(ERC20_TRANSFER_SELECTOR),
                    "operation": SafeOperationEnum.CALL.value,
                    "policy": policy_contract.address,
                    "removed": False,
                    "fallback": False,
                    "data": to_0x_hex_str(bytes(confirmation.data)),
                    "data_decoded": {
                        "policy_name": ERC20_TRANSFER_POLICY,
                        "parameters": {
                            "recipients": [
                                {"recipient": recipients[0], "allowed": True},
                                {"recipient": recipients[1], "allowed": True},
                            ]
                        },
                    },
                    "transaction_hash": confirmation.ethereum_tx_id,
                    "block_number": confirmation.block_number,
                    "log_index": confirmation.log_index,
                    "timestamp": confirmation.timestamp.isoformat().replace(
                        "+00:00", "Z"
                    ),
                }
            ],
        )

    def test_data_decoded_is_null_for_an_unknown_policy(self):
        PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(self.url)

        self.assertIsNone(response.data["results"][0]["data_decoded"])

    def test_ordered_by_newest_first(self):
        oldest = PolicyConfirmationFactory(safe=self.safe)
        newest = PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(self.url)

        self.assertEqual(
            [result["block_number"] for result in response.data["results"]],
            [newest.block_number, oldest.block_number],
        )

        response = self.client.get(self.url, {"ordering": "block_number"})
        self.assertEqual(
            [result["block_number"] for result in response.data["results"]],
            [oldest.block_number, newest.block_number],
        )

    def test_ordered_by_log_index_within_a_transaction(self):
        ethereum_tx = history_factories.EthereumTxFactory()
        PolicyConfirmationFactory(safe=self.safe, ethereum_tx=ethereum_tx, log_index=0)
        PolicyConfirmationFactory(safe=self.safe, ethereum_tx=ethereum_tx, log_index=1)

        response = self.client.get(self.url)

        self.assertEqual(
            [result["log_index"] for result in response.data["results"]], [1, 0]
        )

    def test_filter_target(self):
        confirmation = PolicyConfirmationFactory(safe=self.safe)
        PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(self.url, {"target": confirmation.target})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["target"], confirmation.target)

    def test_filter_selector(self):
        PolicyConfirmationFactory(safe=self.safe, selector=ERC20_TRANSFER_SELECTOR)
        PolicyConfirmationFactory(safe=self.safe, selector=FALLBACK_SELECTOR)

        response = self.client.get(
            self.url, {"selector": to_0x_hex_str(ERC20_TRANSFER_SELECTOR)}
        )

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["selector"],
            to_0x_hex_str(ERC20_TRANSFER_SELECTOR),
        )

    def test_filter_operation(self):
        PolicyConfirmationFactory(
            safe=self.safe, operation=SafeOperationEnum.CALL.value
        )
        PolicyConfirmationFactory(
            safe=self.safe, operation=SafeOperationEnum.DELEGATE_CALL.value
        )

        response = self.client.get(
            self.url, {"operation": SafeOperationEnum.DELEGATE_CALL.value}
        )

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["operation"],
            SafeOperationEnum.DELEGATE_CALL.value,
        )

    def test_filter_policy(self):
        confirmation = PolicyConfirmationFactory(safe=self.safe)
        PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(self.url, {"policy": confirmation.policy})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["policy"], confirmation.policy)

    def test_filter_removed(self):
        PolicyConfirmationFactory(safe=self.safe, policy=NULL_ADDRESS)
        PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(self.url, {"removed": True})
        self.assertEqual(response.data["count"], 1)
        self.assertTrue(response.data["results"][0]["removed"])

        response = self.client.get(self.url, {"removed": False})
        self.assertEqual(response.data["count"], 1)
        self.assertFalse(response.data["results"][0]["removed"])

    def test_filter_fallback(self):
        PolicyConfirmationFactory(
            safe=self.safe, target=NULL_ADDRESS, selector=FALLBACK_SELECTOR
        )
        # Only the target is empty, so it is not the catch-all policy
        PolicyConfirmationFactory(safe=self.safe, target=NULL_ADDRESS)

        response = self.client.get(self.url, {"fallback": True})
        self.assertEqual(response.data["count"], 1)
        self.assertTrue(response.data["results"][0]["fallback"])

        response = self.client.get(self.url, {"fallback": False})
        self.assertEqual(response.data["count"], 1)
        self.assertFalse(response.data["results"][0]["fallback"])

    def test_filter_transaction_hash(self):
        confirmation = PolicyConfirmationFactory(safe=self.safe)
        PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(
            self.url,
            {"transaction_hash": confirmation.ethereum_tx_id},
        )

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["log_index"], confirmation.log_index
        )

    def test_filter_block_number(self):
        oldest = PolicyConfirmationFactory(safe=self.safe)
        newest = PolicyConfirmationFactory(safe=self.safe)

        response = self.client.get(self.url, {"block_number": newest.block_number})
        self.assertEqual(response.data["count"], 1)

        response = self.client.get(self.url, {"block_number__gte": newest.block_number})
        self.assertEqual(response.data["count"], 1)

        response = self.client.get(self.url, {"block_number__lte": oldest.block_number})
        self.assertEqual(response.data["count"], 1)

    def test_filter_timestamp(self):
        confirmation = PolicyConfirmationFactory(safe=self.safe)
        one_hour = datetime.timedelta(hours=1)

        response = self.client.get(
            self.url,
            {"timestamp__gte": (confirmation.timestamp - one_hour).isoformat()},
        )
        self.assertEqual(response.data["count"], 1)

        response = self.client.get(
            self.url,
            {"timestamp__lte": (confirmation.timestamp - one_hour).isoformat()},
        )
        self.assertEqual(response.data["count"], 0)

    def test_pagination(self):
        PolicyConfirmationFactory.create_batch(3, safe=self.safe)

        response = self.client.get(self.url, {"limit": 2})

        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])


class TestSafePolicyRootRequestsView(APITestCase):
    def setUp(self):
        self.safe = Account.create().address
        self.url = reverse("v2:policies:policy-root-requests", args=(self.safe,))
        self.not_elapsed = timezone.now() + datetime.timedelta(hours=1)
        self.elapsed = timezone.now() - datetime.timedelta(hours=1)

    def test_invalid_address(self):
        response = self.client.get(
            reverse("v2:policies:policy-root-requests", args=("0x1234",))
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_empty(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 0)

    def test_only_returns_the_requested_safe(self):
        PolicyRootRequestFactory(safe=self.safe)
        PolicyRootRequestFactory()

        response = self.client.get(self.url)

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["safe"], self.safe)

    def test_response(self):
        request = PolicyRootRequestFactory(safe=self.safe, valid_from=self.not_elapsed)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["results"],
            [
                {
                    "safe": self.safe,
                    "guard": request.guard,
                    "root": request.root,
                    "valid_from": self.not_elapsed.isoformat().replace("+00:00", "Z"),
                    "status": PolicyRootStatus.PENDING,
                    "invalidated_at": None,
                    "transaction_hash": request.ethereum_tx_id,
                    "block_number": request.block_number,
                    "log_index": request.log_index,
                    "timestamp": request.timestamp.isoformat().replace("+00:00", "Z"),
                }
            ],
        )

    def test_status_ready(self):
        PolicyRootRequestFactory(safe=self.safe, valid_from=self.elapsed)

        response = self.client.get(self.url)

        self.assertEqual(response.data["results"][0]["status"], PolicyRootStatus.READY)

    def test_status_invalidated(self):
        request = PolicyRootRequestFactory(safe=self.safe, valid_from=self.not_elapsed)
        invalidation = PolicyRootInvalidationFactory(safe=self.safe, root=request.root)

        response = self.client.get(self.url)

        result = response.data["results"][0]
        self.assertEqual(result["status"], PolicyRootStatus.INVALIDATED)
        self.assertEqual(
            result["invalidated_at"],
            invalidation.timestamp.isoformat().replace("+00:00", "Z"),
        )

    def test_filter_status(self):
        pending = PolicyRootRequestFactory(safe=self.safe, valid_from=self.not_elapsed)
        PolicyRootRequestFactory(safe=self.safe, valid_from=self.elapsed)
        invalidated = PolicyRootRequestFactory(
            safe=self.safe, valid_from=self.not_elapsed
        )
        PolicyRootInvalidationFactory(safe=self.safe, root=invalidated.root)

        for root_status, expected in (
            (PolicyRootStatus.PENDING, pending.root),
            (PolicyRootStatus.INVALIDATED, invalidated.root),
        ):
            with self.subTest(status=root_status):
                response = self.client.get(self.url, {"status": root_status.value})
                self.assertEqual(response.data["count"], 1)
                self.assertEqual(response.data["results"][0]["root"], expected)

        response = self.client.get(self.url, {"status": PolicyRootStatus.READY.value})
        self.assertEqual(response.data["count"], 1)

    def test_filter_invalid_status(self):
        response = self.client.get(self.url, {"status": "applied"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_root(self):
        request = PolicyRootRequestFactory(safe=self.safe)
        PolicyRootRequestFactory(safe=self.safe)

        response = self.client.get(self.url, {"root": request.root})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["root"], request.root)

    def test_filter_valid_from(self):
        PolicyRootRequestFactory(safe=self.safe, valid_from=self.not_elapsed)
        PolicyRootRequestFactory(safe=self.safe, valid_from=self.elapsed)
        now = timezone.now().isoformat()

        response = self.client.get(self.url, {"valid_from__gte": now})
        self.assertEqual(response.data["count"], 1)

        response = self.client.get(self.url, {"valid_from__lte": now})
        self.assertEqual(response.data["count"], 1)

    def test_filter_transaction_hash(self):
        request = PolicyRootRequestFactory(safe=self.safe)
        PolicyRootRequestFactory(safe=self.safe)

        response = self.client.get(
            self.url,
            {"transaction_hash": request.ethereum_tx_id},
        )

        self.assertEqual(response.data["count"], 1)

    def test_ordered_by_newest_first(self):
        oldest = PolicyRootRequestFactory(safe=self.safe)
        newest = PolicyRootRequestFactory(safe=self.safe)

        response = self.client.get(self.url)

        self.assertEqual(
            [result["block_number"] for result in response.data["results"]],
            [newest.block_number, oldest.block_number],
        )


class TestPolicySchema(APITestCase):
    def test_endpoints_are_on_the_openapi_schema(self):
        response = self.client.get(reverse("schema-json") + "?format=json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        paths = response.json()["paths"]
        for path in (
            "/api/v2/safes/{address}/policy-confirmations/",
            "/api/v2/safes/{address}/policy-root-requests/",
        ):
            with self.subTest(path=path):
                self.assertIn(path, paths)
                self.assertEqual(paths[path]["get"]["tags"], ["policies"])

    def test_filters_are_documented(self):
        response = self.client.get(reverse("schema-json") + "?format=json")

        parameters = response.json()["paths"][
            "/api/v2/safes/{address}/policy-confirmations/"
        ]["get"]["parameters"]
        self.assertLessEqual(
            {"target", "selector", "operation", "policy", "removed", "fallback"},
            {parameter["name"] for parameter in parameters},
        )


class TestPolicyDecoderIsSharedWithTheApi(APITestCase):
    def test_a_new_policy_contract_changes_the_response_without_reindexing(self):
        """`data` is decoded on read, so registering a policy needs no backfill"""
        safe = Account.create().address
        cosigner = Account.create().address
        # `CoSignerPolicy` data, indexed before the policy contract is known
        confirmation = PolicyConfirmationFactory(
            safe=safe,
            selector=FALLBACK_SELECTOR,
            data=encode_abi(["address"], [cosigner]),
        )
        url = reverse("v2:policies:policy-confirmations", args=(safe,))

        self.assertIsNone(self.client.get(url).data["results"][0]["data_decoded"])

        PolicyContractFactory(address=confirmation.policy, name=COSIGNER_POLICY)

        self.assertEqual(
            self.client.get(url).data["results"][0]["data_decoded"],
            {"policy_name": COSIGNER_POLICY, "parameters": {"cosigner": cosigner}},
        )
