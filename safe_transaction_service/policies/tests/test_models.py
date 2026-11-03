# SPDX-License-Identifier: FSL-1.1-MIT
import datetime

from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.safe.enums import SafeOperationEnum

from safe_transaction_service.history.tests import factories as history_factories

from ..models import (
    FALLBACK_SELECTOR,
    PolicyConfirmation,
    PolicyRootRequest,
    PolicyRootStatus,
)
from .factories import (
    ERC20_TRANSFER_SELECTOR,
    PolicyConfirmationFactory,
    PolicyRootInvalidationFactory,
    PolicyRootRequestFactory,
)

# `EthereumBlockFactory` numbers blocks with an increasing sequence, so creating events in
# chronological order is enough to control their relative order


class TestPolicyConfirmation(TestCase):
    def test_removed(self):
        self.assertFalse(PolicyConfirmationFactory().removed)
        self.assertTrue(PolicyConfirmationFactory(policy=NULL_ADDRESS).removed)

    def test_fallback(self):
        self.assertFalse(PolicyConfirmationFactory().fallback)
        self.assertTrue(
            PolicyConfirmationFactory(
                target=NULL_ADDRESS, selector=FALLBACK_SELECTOR
            ).fallback
        )
        # Both must be empty
        self.assertFalse(PolicyConfirmationFactory(target=NULL_ADDRESS).fallback)
        self.assertFalse(PolicyConfirmationFactory(selector=FALLBACK_SELECTOR).fallback)

    def test_removed_and_fallback_after_reload(self):
        """`selector` is a `memoryview` and `policy` a `str` when read from the database"""
        PolicyConfirmationFactory(
            policy=NULL_ADDRESS, target=NULL_ADDRESS, selector=FALLBACK_SELECTOR
        )

        confirmation = PolicyConfirmation.objects.get()
        self.assertTrue(confirmation.removed)
        self.assertTrue(confirmation.fallback)


class TestPolicyConfirmationQuerySet(TestCase):
    def setUp(self):
        self.safe = Account.create().address
        self.policy = Account.create().address
        self.access = {
            "safe": self.safe,
            "target": Account.create().address,
            "selector": ERC20_TRANSFER_SELECTOR,
            "operation": SafeOperationEnum.CALL.value,
        }

    def test_current_keeps_the_latest_per_access_selector(self):
        PolicyConfirmationFactory(policy=self.policy, **self.access)
        removal = PolicyConfirmationFactory(policy=NULL_ADDRESS, **self.access)

        self.assertEqual(list(PolicyConfirmation.objects.current()), [removal])
        # A removal is not an enforced policy
        self.assertEqual(list(PolicyConfirmation.objects.active()), [])

        # Setting it again restores it
        re_added = PolicyConfirmationFactory(policy=self.policy, **self.access)
        self.assertEqual(list(PolicyConfirmation.objects.current()), [re_added])
        self.assertEqual(list(PolicyConfirmation.objects.active()), [re_added])

    def test_current_breaks_ties_by_log_index(self):
        ethereum_tx = history_factories.EthereumTxFactory()
        PolicyConfirmationFactory(
            ethereum_tx=ethereum_tx, log_index=0, policy=self.policy, **self.access
        )
        last = PolicyConfirmationFactory(
            ethereum_tx=ethereum_tx, log_index=1, policy=NULL_ADDRESS, **self.access
        )

        self.assertEqual(list(PolicyConfirmation.objects.current()), [last])

    def test_current_keeps_access_selectors_apart(self):
        access = {
            "safe": self.safe,
            "target": self.access["target"],
            "policy": self.policy,
        }
        PolicyConfirmationFactory(
            selector=ERC20_TRANSFER_SELECTOR,
            operation=SafeOperationEnum.CALL.value,
            **access,
        )
        # Same target and selector, different operation
        PolicyConfirmationFactory(
            selector=ERC20_TRANSFER_SELECTOR,
            operation=SafeOperationEnum.DELEGATE_CALL.value,
            **access,
        )
        # Same target and operation, different selector
        PolicyConfirmationFactory(
            selector=FALLBACK_SELECTOR,
            operation=SafeOperationEnum.CALL.value,
            **access,
        )

        self.assertEqual(PolicyConfirmation.objects.current().count(), 3)


class TestPolicyRootRequestQuerySet(TestCase):
    def setUp(self):
        self.not_elapsed = timezone.now() + datetime.timedelta(hours=1)
        self.elapsed = timezone.now() - datetime.timedelta(hours=1)

    def test_status_pending(self):
        request = PolicyRootRequestFactory(valid_from=self.not_elapsed)

        annotated = PolicyRootRequest.objects.with_status().get(pk=request.pk)
        self.assertEqual(annotated.status, PolicyRootStatus.PENDING)
        self.assertIsNone(annotated.invalidated_at)

    def test_status_ready(self):
        request = PolicyRootRequestFactory(valid_from=self.elapsed)

        self.assertEqual(
            PolicyRootRequest.objects.with_status().get(pk=request.pk).status,
            PolicyRootStatus.READY,
        )

    def test_status_invalidated(self):
        request = PolicyRootRequestFactory(valid_from=self.not_elapsed)
        invalidation = PolicyRootInvalidationFactory(
            safe=request.safe, root=request.root
        )

        annotated = PolicyRootRequest.objects.with_status().get(pk=request.pk)
        self.assertEqual(annotated.status, PolicyRootStatus.INVALIDATED)
        self.assertEqual(annotated.invalidated_at, invalidation.timestamp)

    def test_status_ignores_other_safe_and_root(self):
        request = PolicyRootRequestFactory(valid_from=self.not_elapsed)
        # Same root, another Safe
        PolicyRootInvalidationFactory(root=request.root)
        # Same Safe, another root
        PolicyRootInvalidationFactory(safe=request.safe)

        self.assertEqual(
            PolicyRootRequest.objects.with_status().get(pk=request.pk).status,
            PolicyRootStatus.PENDING,
        )

    def test_status_ignores_earlier_invalidation(self):
        """A root can be requested again after being invalidated"""
        safe, root = Account.create().address, "0x" + "11" * 32
        first_request = PolicyRootRequestFactory(
            safe=safe, root=root, valid_from=self.elapsed
        )
        PolicyRootInvalidationFactory(safe=safe, root=root)
        second_request = PolicyRootRequestFactory(
            safe=safe, root=root, valid_from=self.elapsed
        )

        annotated = PolicyRootRequest.objects.with_status()
        self.assertEqual(
            annotated.get(pk=first_request.pk).status, PolicyRootStatus.INVALIDATED
        )
        self.assertEqual(
            annotated.get(pk=second_request.pk).status, PolicyRootStatus.READY
        )

    def test_status_uses_the_first_invalidation_after_the_request(self):
        safe, root = Account.create().address, "0x" + "22" * 32
        request = PolicyRootRequestFactory(
            safe=safe, root=root, valid_from=self.elapsed
        )
        first_invalidation = PolicyRootInvalidationFactory(safe=safe, root=root)
        PolicyRootInvalidationFactory(safe=safe, root=root)

        self.assertEqual(
            PolicyRootRequest.objects.with_status().get(pk=request.pk).invalidated_at,
            first_invalidation.timestamp,
        )
