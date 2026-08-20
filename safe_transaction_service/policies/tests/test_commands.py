# SPDX-License-Identifier: FSL-1.1-MIT
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from django_celery_beat.models import PeriodicTask
from eth_account import Account

from safe_transaction_service.history.management.commands.setup_service import (
    TASKS,
)
from safe_transaction_service.history.management.commands.setup_service import (
    Command as SetupServiceCommand,
)

from ..constants import GUARD_DEPLOYMENTS, POLICY_DEPLOYMENTS
from ..models import PolicyContract, SafePolicyGuard
from .factories import SafePolicyGuardFactory

INDEX_POLICY_EVENTS_TASK = (
    "safe_transaction_service.policies.tasks.index_policy_events_task"
)


class TestSetupPolicyEngine(TestCase):
    """`setup_service` seeds the guards to index and the decodable policies"""

    def setUp(self):
        self.command = SetupServiceCommand(stdout=StringIO())
        for task in TASKS:
            if task.name == INDEX_POLICY_EVENTS_TASK:
                task.create_task()

    def _is_task_enabled(self) -> bool:
        return PeriodicTask.objects.get(task=INDEX_POLICY_EVENTS_TASK).enabled

    def test_known_chain(self):
        chain_id = 11155111
        self.command._setup_policy_engine(chain_id)

        self.assertCountEqual(
            SafePolicyGuard.objects.values_list("address", flat=True),
            [deployment.address for deployment in GUARD_DEPLOYMENTS[chain_id]],
        )
        self.assertEqual(
            PolicyContract.objects.count(), len(POLICY_DEPLOYMENTS[chain_id])
        )
        self.assertTrue(self._is_task_enabled())

    def test_unknown_chain_disables_indexing(self):
        self.command._setup_policy_engine(1337)

        self.assertEqual(SafePolicyGuard.objects.count(), 0)
        self.assertEqual(PolicyContract.objects.count(), 0)
        self.assertFalse(self._is_task_enabled())

    @override_settings(POLICIES_ENABLE_INDEXING=False)
    def test_setting_disables_indexing_on_a_known_chain(self):
        self.command._setup_policy_engine(11155111)

        self.assertEqual(SafePolicyGuard.objects.count(), 0)
        self.assertEqual(PolicyContract.objects.count(), 0)
        self.assertFalse(self._is_task_enabled())

    def test_seeds_the_deployment_block_number(self):
        chain_id = 11155111
        self.command._setup_policy_engine(chain_id)

        guard = SafePolicyGuard.objects.get(
            address=GUARD_DEPLOYMENTS[chain_id][0].address
        )
        # Indexing must start at the deployment block, not at 0
        self.assertEqual(
            guard.initial_block_number,
            GUARD_DEPLOYMENTS[chain_id][0].initial_block_number,
        )
        self.assertEqual(guard.tx_block_number, guard.initial_block_number)

    def test_is_idempotent(self):
        chain_id = 11155111
        self.command._setup_policy_engine(chain_id)
        guard = SafePolicyGuard.objects.first()
        guard.tx_block_number = 5_000
        guard.save(update_fields=["tx_block_number"])

        self.command._setup_policy_engine(chain_id)

        # Running it again must not rewind the indexing progress of a known guard
        guard.refresh_from_db()
        self.assertEqual(guard.tx_block_number, 5_000)
        self.assertEqual(
            SafePolicyGuard.objects.count(), len(GUARD_DEPLOYMENTS[chain_id])
        )
        self.assertEqual(
            PolicyContract.objects.count(), len(POLICY_DEPLOYMENTS[chain_id])
        )


class TestReindexPolicies(TestCase):
    def test_rewinds_every_guard(self):
        SafePolicyGuardFactory(tx_block_number=100)
        SafePolicyGuardFactory(tx_block_number=200)
        buffer = StringIO()

        call_command("reindex_policies", "--from-block-number=50", stdout=buffer)

        self.assertIn("Rewound 2 guard(s) to block-number=50", buffer.getvalue())
        self.assertEqual(
            list(SafePolicyGuard.objects.values_list("tx_block_number", flat=True)),
            [50, 50],
        )

    def test_rewinds_only_the_given_guards(self):
        guard = SafePolicyGuardFactory(tx_block_number=100)
        untouched = SafePolicyGuardFactory(tx_block_number=200)

        call_command(
            "reindex_policies",
            "--from-block-number=50",
            f"--addresses={guard.address}",
            stdout=StringIO(),
        )

        guard.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(guard.tx_block_number, 50)
        self.assertEqual(untouched.tx_block_number, 200)

    def test_never_moves_the_cursor_forward(self):
        guard = SafePolicyGuardFactory(tx_block_number=100)
        buffer = StringIO()

        call_command("reindex_policies", "--from-block-number=200", stdout=buffer)

        guard.refresh_from_db()
        self.assertEqual(guard.tx_block_number, 100)
        self.assertIn("Rewound 0 guard(s)", buffer.getvalue())

    def test_unknown_address(self):
        SafePolicyGuardFactory()

        with self.assertRaisesMessage(CommandError, "are monitored guards"):
            call_command(
                "reindex_policies",
                "--from-block-number=50",
                f"--addresses={Account.create().address}",
            )

    def test_negative_block_number(self):
        with self.assertRaisesMessage(CommandError, "cannot be negative"):
            call_command("reindex_policies", "--from-block-number=-1")
