import json

from django.test import TestCase

import pytest
from django_test_migrations.migrator import Migrator
from eth_account import Account
from web3 import Web3


class TestMigrations(TestCase):
    @pytest.mark.django_db
    def test_migration_forward_0068(self):
        migrator = Migrator(database="default")
        old_state = migrator.apply_initial_migration(
            ("history", "0067_auto_20220705_1545")
        )
        MultisigTransactionOld = old_state.apps.get_model(
            "history", "MultisigTransaction"
        )
        origins = [
            "{ {TestString",
            '{"url":"https://example.com", "name":"app"}',
            "",
            None,
        ]
        for origin in origins:
            MultisigTransactionOld.objects.create(
                safe_tx_hash=Web3.keccak(text=f"multisig-tx-{origin}").hex(),
                safe=Account.create().address,
                value=0,
                operation=0,
                safe_tx_gas=0,
                base_gas=0,
                gas_price=0,
                nonce=0,
                origin=origin,
            )

        new_state = migrator.apply_tested_migration(
            ("history", "0068_alter_multisigtransaction_origin"),
        )
        MultisigTransactionNew = new_state.apps.get_model(
            "history", "Multisigtransaction"
        )

        # String should keep string
        hash = Web3.keccak(text=f"multisig-tx-{origins[0]}").hex()
        self.assertEqual(MultisigTransactionNew.objects.get(pk=hash).origin, origins[0])

        # String json should be converted to json
        hash = Web3.keccak(text=f"multisig-tx-{origins[1]}").hex()
        self.assertEqual(
            MultisigTransactionNew.objects.get(pk=hash).origin, json.loads(origins[1])
        )

        # Empty string should be empty object
        hash = Web3.keccak(text=f"multisig-tx-{origins[2]}").hex()
        self.assertEqual(MultisigTransactionNew.objects.get(pk=hash).origin, {})

        # None should be empty object
        hash = Web3.keccak(text=f"multisig-tx-{origins[2]}").hex()
        self.assertEqual(MultisigTransactionNew.objects.get(pk=hash).origin, {})

    @pytest.mark.django_db
    def test_migration_backward_0068(self):
        migrator = Migrator(database="default")
        new_state = migrator.apply_initial_migration(
            ("history", "0068_alter_multisigtransaction_origin")
        )
        MultisigTransactionNew = new_state.apps.get_model(
            "history", "MultisigTransaction"
        )
        origins = ["{ TestString", {"url": "https://example.com", "name": "app"}, {}]
        for origin in origins:
            MultisigTransactionNew.objects.create(
                safe_tx_hash=Web3.keccak(text=f"multisig-tx-{origin}").hex(),
                safe=Account.create().address,
                value=0,
                operation=0,
                safe_tx_gas=0,
                base_gas=0,
                gas_price=0,
                nonce=0,
                origin=origin,
            )

        old_state = migrator.apply_tested_migration(
            ("history", "0067_auto_20220705_1545"),
        )
        MultisigTransactionOld = old_state.apps.get_model(
            "history", "Multisigtransaction"
        )

        # String should keep string
        hash = Web3.keccak(text=f"multisig-tx-{origins[0]}").hex()
        self.assertEqual(MultisigTransactionOld.objects.get(pk=hash).origin, origins[0])

        # Json should be converted to a string json
        hash = Web3.keccak(text=f"multisig-tx-{origins[1]}").hex()
        self.assertEqual(
            MultisigTransactionOld.objects.get(pk=hash).origin, json.dumps(origins[1])
        )

        # Empty object should be None
        hash = Web3.keccak(text=f"multisig-tx-{origins[2]}").hex()
        self.assertEqual(MultisigTransactionOld.objects.get(pk=hash).origin, None)

    def test_migration_forward_0069(self):
        pass

    def test_migration_backward_0069(self):
        pass
