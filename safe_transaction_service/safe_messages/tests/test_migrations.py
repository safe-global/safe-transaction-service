from unittest import mock
from unittest.mock import PropertyMock

from django.test import TestCase

from django_test_migrations.migrator import Migrator
from safe_eth.safe import Safe
from safe_eth.safe.safe_signature import SafeSignatureType

from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
)


class TestMigrations(TestCase):
    def setUp(self) -> None:
        self.migrator = Migrator(database="default")

    @mock.patch.object(
        Safe, "domain_separator", new_callable=mock.PropertyMock, return_value=b"23"
    )
    def test_migration_forward_0006_remove_contract_signatures(
        self, domain_separator_mock: PropertyMock
    ):
        old_state = self.migrator.apply_initial_migration(
            ("safe_messages", "0005_safemessage_origin")
        )
        SafeMessageConfirmationFactory(
            signature_type=SafeSignatureType.CONTRACT_SIGNATURE.value
        )
        SafeMessageConfirmationFactory(signature_type=SafeSignatureType.EOA.value)
        SafeMessageConfirmationFactory(
            signature_type=SafeSignatureType.APPROVED_HASH.value
        )
        SafeMessageConfirmationFactory(
            signature_type=SafeSignatureType.CONTRACT_SIGNATURE.value
        )

        SafeMessageOld = old_state.apps.get_model("safe_messages", "SafeMessage")
        SafeMessageConfirmationOld = old_state.apps.get_model(
            "safe_messages", "SafeMessageConfirmation"
        )
        self.assertEqual(SafeMessageOld.objects.count(), 4)
        self.assertEqual(SafeMessageConfirmationOld.objects.count(), 4)
        self.assertEqual(
            SafeMessageConfirmationOld.objects.filter(
                signature_type=SafeSignatureType.CONTRACT_SIGNATURE.value
            ).count(),
            2,
        )

        new_state = self.migrator.apply_tested_migration(
            ("safe_messages", "0006_remove_contract_signatures"),
        )
        SafeMessageNew = old_state.apps.get_model("safe_messages", "SafeMessage")
        SafeMessageConfirmationNew = new_state.apps.get_model(
            "safe_messages", "SafeMessageConfirmation"
        )
        self.assertEqual(SafeMessageNew.objects.count(), 4)
        self.assertEqual(SafeMessageConfirmationNew.objects.count(), 2)
        self.assertEqual(
            SafeMessageConfirmationNew.objects.filter(
                signature_type=SafeSignatureType.CONTRACT_SIGNATURE.value
            ).count(),
            0,
        )
