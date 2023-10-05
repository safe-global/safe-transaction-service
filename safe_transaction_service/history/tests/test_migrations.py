import json

from django.test import TestCase
from django.utils import timezone

from django_test_migrations.migrator import Migrator
from eth_account import Account
from web3 import Web3


class TestMigrations(TestCase):
    def setUp(self) -> None:
        self.migrator = Migrator(database="default")

    def build_ethereum_tx(self, ethereum_block_class, ethereum_tx_class):
        """
        Factory boy does not work with migrations

        :param ethereum_block_class:
        :param ethereum_tx_class:
        :return: Instance of EthereumTx
        """
        ethereum_block = ethereum_block_class.objects.create(
            number=1,
            gas_limit=2,
            gas_used=2,
            timestamp=timezone.now(),
            block_hash=Web3.keccak(b"34"),
            parent_hash=Web3.keccak(b"12"),
        )

        return ethereum_tx_class.objects.create(
            block=ethereum_block,
            tx_hash=Web3.keccak(b"tx-hash"),
            gas=23000,
            gas_price=1,
            nonce=0,
            value=0,
        )

    def test_migration_forward_0068(self):
        old_state = self.migrator.apply_initial_migration(
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

        new_state = self.migrator.apply_tested_migration(
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

    def test_migration_backward_0068(self):
        new_state = self.migrator.apply_initial_migration(
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

        old_state = self.migrator.apply_tested_migration(
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
        old_state = self.migrator.apply_initial_migration(
            ("history", "0068_alter_multisigtransaction_origin")
        )

        EthereumBlock = old_state.apps.get_model("history", "EthereumBlock")
        EthereumTx = old_state.apps.get_model("history", "EthereumTx")
        ethereum_tx = self.build_ethereum_tx(EthereumBlock, EthereumTx)
        SafeContract = old_state.apps.get_model("history", "SafeContract")
        SafeContract.objects.create(
            address=Account.create().address,
            erc20_block_number=8,
            ethereum_tx=ethereum_tx,
        )
        SafeContract.objects.create(
            address=Account.create().address,
            erc20_block_number=4,
            ethereum_tx=ethereum_tx,
        )
        SafeContract.objects.create(
            address=Account.create().address,
            erc20_block_number=15,
            ethereum_tx=ethereum_tx,
        )
        new_state = self.migrator.apply_tested_migration(
            ("history", "0069_indexingstatus_and_more"),
        )
        IndexingStatus = new_state.apps.get_model("history", "IndexingStatus")
        self.assertEqual(IndexingStatus.objects.get().block_number, 4)

    def test_migration_forward_0069_using_master_copies(self):
        old_state = self.migrator.apply_initial_migration(
            ("history", "0068_alter_multisigtransaction_origin")
        )

        SafeMasterCopy = old_state.apps.get_model("history", "SafeMasterCopy")
        SafeMasterCopy.objects.create(
            address=Account.create().address,
            initial_block_number=15,
            tx_block_number=23,
            l2=False,
        )
        SafeMasterCopy.objects.create(
            address=Account.create().address,
            initial_block_number=16,
            tx_block_number=42,
            l2=True,
        )

        new_state = self.migrator.apply_tested_migration(
            ("history", "0069_indexingstatus_and_more"),
        )
        IndexingStatus = new_state.apps.get_model("history", "IndexingStatus")
        self.assertEqual(IndexingStatus.objects.get().block_number, 15)

    def test_migration_backward_0069(self):
        new_state = self.migrator.apply_initial_migration(
            ("history", "0069_indexingstatus_and_more"),
        )
        IndexingStatus = new_state.apps.get_model("history", "IndexingStatus")
        self.assertEqual(IndexingStatus.objects.get().block_number, 0)
        IndexingStatus.objects.update(block_number=4)

        EthereumBlock = new_state.apps.get_model("history", "EthereumBlock")
        EthereumTx = new_state.apps.get_model("history", "EthereumTx")
        SafeContract = new_state.apps.get_model("history", "SafeContract")
        ethereum_tx = self.build_ethereum_tx(EthereumBlock, EthereumTx)
        SafeContract.objects.create(
            address=Account.create().address, ethereum_tx=ethereum_tx
        )
        SafeContract.objects.create(
            address=Account.create().address, ethereum_tx=ethereum_tx
        )
        SafeContract.objects.create(
            address=Account.create().address, ethereum_tx=ethereum_tx
        )

        old_state = self.migrator.apply_tested_migration(
            ("history", "0068_alter_multisigtransaction_origin")
        )
        SafeContract = old_state.apps.get_model("history", "SafeContract")
        self.assertEqual(SafeContract.objects.filter(erc20_block_number=4).count(), 3)

    def test_migration_backward_0069_db_empty(self):
        new_state = self.migrator.apply_initial_migration(
            ("history", "0069_indexingstatus_and_more"),
        )
        IndexingStatus = new_state.apps.get_model("history", "IndexingStatus")
        self.assertEqual(IndexingStatus.objects.get().block_number, 0)
        IndexingStatus.objects.all().delete()

        EthereumBlock = new_state.apps.get_model("history", "EthereumBlock")
        EthereumTx = new_state.apps.get_model("history", "EthereumTx")
        SafeContract = new_state.apps.get_model("history", "SafeContract")
        ethereum_tx = self.build_ethereum_tx(EthereumBlock, EthereumTx)
        SafeContract.objects.create(
            address=Account.create().address, ethereum_tx=ethereum_tx
        )
        SafeContract.objects.create(
            address=Account.create().address, ethereum_tx=ethereum_tx
        )
        SafeContract.objects.create(
            address=Account.create().address, ethereum_tx=ethereum_tx
        )

        old_state = self.migrator.apply_tested_migration(
            ("history", "0068_alter_multisigtransaction_origin")
        )
        SafeContract = old_state.apps.get_model("history", "SafeContract")
        self.assertEqual(SafeContract.objects.filter(erc20_block_number=0).count(), 3)

    def test_migration_forward_0073_safe_apps_links(self):
        """
        Migrate safe apps links from 'apps.gnosis-safe.io' -> 'apps-portal.safe.global'
        """

        new_state = self.migrator.apply_initial_migration(
            ("history", "0072_safecontract_banned_and_more"),
        )
        origins = [
            {"not_url": "random"},
            {"url": "https://app.zerion.io", "name": "Zerion"},
            {
                "url": "https://apps.gnosis-safe.io/tx-builder/",
                "name": "Transaction Builder",
            },
        ]

        MultisigTransaction = new_state.apps.get_model("history", "MultisigTransaction")
        for origin in origins:
            MultisigTransaction.objects.create(
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

        new_state = self.migrator.apply_tested_migration(
            ("history", "0073_safe_apps_links"),
        )
        MultisigTransaction = new_state.apps.get_model("history", "MultisigTransaction")
        self.assertCountEqual(
            MultisigTransaction.objects.values_list("origin", flat=True),
            [
                {"not_url": "random"},
                {"url": "https://app.zerion.io", "name": "Zerion"},
                {
                    "url": "https://apps-portal.safe.global/tx-builder/",
                    "name": "Transaction Builder",
                },
            ],
        )

    def test_migration_backward_0073_safe_apps_links(self):
        """
        Migrate safe apps links from 'apps.gnosis-safe.io' -> 'apps-portal.safe.global'
        """

        new_state = self.migrator.apply_initial_migration(
            ("history", "0073_safe_apps_links"),
        )

        origins = [
            {"not_url": "random"},
            {"url": "https://app.zerion.io", "name": "Zerion"},
            {
                "url": "https://apps.gnosis-safe.io/tx-builder/",
                "name": "Transaction Builder",
            },
        ]

        MultisigTransaction = new_state.apps.get_model("history", "MultisigTransaction")
        for origin in origins:
            MultisigTransaction.objects.create(
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

        new_state = self.migrator.apply_tested_migration(
            ("history", "0072_safecontract_banned_and_more"),
        )

        MultisigTransaction = new_state.apps.get_model("history", "MultisigTransaction")
        self.assertCountEqual(
            MultisigTransaction.objects.values_list("origin", flat=True),
            [
                {"not_url": "random"},
                {"url": "https://app.zerion.io", "name": "Zerion"},
                {
                    "url": "https://apps.gnosis-safe.io/tx-builder/",
                    "name": "Transaction Builder",
                },
            ],
        )
