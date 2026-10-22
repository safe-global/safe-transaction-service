# SPDX-License-Identifier: FSL-1.1-MIT
from unittest import mock

from django.test import TestCase, override_settings

from ..tasks import index_policy_events_task


class TestIndexPolicyEventsTask(TestCase):
    @override_settings(POLICIES_ENABLE_INDEXING=False)
    @mock.patch("safe_transaction_service.policies.tasks.PolicyEventsIndexerProvider")
    def test_disabled_by_setting(self, provider_mock: mock.MagicMock):
        # A schedule enabled before the flag was turned off must not index anything
        self.assertIsNone(index_policy_events_task())

        provider_mock.assert_not_called()

    @override_settings(POLICIES_ENABLE_INDEXING=True)
    @mock.patch("safe_transaction_service.policies.tasks.PolicyEventsIndexerProvider")
    def test_enabled_runs_the_indexer(self, provider_mock: mock.MagicMock):
        provider_mock.return_value.start.return_value = (3, 10)

        self.assertEqual(index_policy_events_task(), (3, 10))
