from django.test import TestCase

from django_test_migrations.migrator import Migrator
from eth_account import Account
from hexbytes import HexBytes

from gnosis.eth.utils import fast_keccak_text
from gnosis.safe.safe_signature import SafeSignatureApprovedHash


class TestMigrations(TestCase):
    def setUp(self) -> None:
        self.migrator = Migrator(database="default")

    def test_migration_forward_0003_alter_safemessageconfirmation_signature(self):
        old_state = self.migrator.apply_initial_migration(
            (
                "safe_messages",
                "0002_alter_safemessageconfirmation_unique_together_and_more",
            ),
        )

        SafeMessageConfirmation = old_state.apps.get_model(
            "safe_messages", "SafeMessageConfirmation"
        )

        owner = Account.create().address
        safe_tx_hash = fast_keccak_text("tx-hash")
        safe_signature = SafeSignatureApprovedHash.build_for_owner(owner, safe_tx_hash)

        SafeMessageConfirmation.objects.create(
            owner=Account.create().address,
            signature=safe_signature.export_signature(),
            signature_type=safe_signature.signature_type.value,
        )

        self.assertEqual(
            HexBytes(SafeMessageConfirmation.objects.get().signature),
            safe_signature.export_signature(),
        )

        new_state = self.migrator.apply_tested_migration(
            ("safe_messages", "0003_alter_safemessageconfirmation_signature"),
        )

        SafeMessageConfirmation = new_state.apps.get_model(
            "safe_messages", "SafeMessageConfirmation"
        )
        self.assertEqual(
            HexBytes(SafeMessageConfirmation.objects.get().signature),
            safe_signature.export_signature(),
        )

    def test_migration_backward_0003_alter_safemessageconfirmation_signature(self):
        new_state = self.migrator.apply_initial_migration(
            ("safe_messages", "0003_alter_safemessageconfirmation_signature"),
        )

        SafeMessageConfirmation = new_state.apps.get_model(
            "safe_messages", "SafeMessageConfirmation"
        )

        owner = Account.create().address
        safe_tx_hash = fast_keccak_text("tx-hash")
        safe_signature = SafeSignatureApprovedHash.build_for_owner(owner, safe_tx_hash)

        SafeMessageConfirmation.objects.create(
            owner=Account.create().address,
            signature=safe_signature.export_signature(),
            signature_type=safe_signature.signature_type.value,
        )

        self.assertEqual(
            HexBytes(SafeMessageConfirmation.objects.get().signature),
            safe_signature.export_signature(),
        )

        old_state = self.migrator.apply_tested_migration(
            (
                "safe_messages",
                "0002_alter_safemessageconfirmation_unique_together_and_more",
            ),
        )

        SafeMessageConfirmation = old_state.apps.get_model(
            "safe_messages", "SafeMessageConfirmation"
        )
        self.assertEqual(
            HexBytes(SafeMessageConfirmation.objects.get().signature),
            safe_signature.export_signature(),
        )
