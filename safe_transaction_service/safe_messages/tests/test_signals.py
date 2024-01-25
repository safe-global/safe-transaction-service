from unittest import mock
from unittest.mock import MagicMock

from django.db.models.signals import post_save
from django.test import TestCase

import factory

from gnosis.eth import EthereumNetwork
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_transaction_service.events.services.queue_service import QueueService
from safe_transaction_service.history.models import WebHookType
from safe_transaction_service.history.tasks import send_webhook_task
from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.safe_messages.signals import process_webhook
from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)


class TestSafeMessageSignals(SafeTestCaseMixin, TestCase):
    @factory.django.mute_signals(post_save)
    @mock.patch.object(send_webhook_task, "apply_async")
    @mock.patch.object(QueueService, "send_event")
    def test_process_webhook(
        self,
        send_event_to_queue_task_mock: MagicMock,
        webhook_task_mock: MagicMock,
    ):
        safe_address = self.deploy_test_safe().address
        safe_message = SafeMessageFactory(safe=safe_address)
        process_webhook(SafeMessage, safe_message, True)
        message_created_payload = {
            "address": safe_address,
            "type": WebHookType.MESSAGE_CREATED.name,
            "messageHash": safe_message.message_hash,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        webhook_task_mock.assert_called_with(
            args=(safe_address, message_created_payload), priority=2
        )
        send_event_to_queue_task_mock.assert_called_with(message_created_payload)

        message_confirmation_payload = {
            "address": safe_address,
            "type": WebHookType.MESSAGE_CONFIRMATION.name,
            "messageHash": safe_message.message_hash,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        process_webhook(SafeMessageConfirmation, safe_message_confirmation, True)
        webhook_task_mock.assert_called_with(
            args=(safe_address, message_confirmation_payload), priority=2
        )

    @mock.patch.object(send_webhook_task, "apply_async")
    @mock.patch.object(QueueService, "send_event")
    def test_signals_are_correctly_fired(
        self,
        send_event_mock: MagicMock,
        webhook_task_mock: MagicMock,
    ):
        safe_address = self.deploy_test_safe().address
        # Create a confirmation should fire a signal and webhooks should be sended
        safe_message = SafeMessageFactory(safe=safe_address)
        message_created_payload = {
            "address": safe_address,
            "type": WebHookType.MESSAGE_CREATED.name,
            "messageHash": safe_message.message_hash,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        webhook_task_mock.assert_called_with(
            args=(safe_address, message_created_payload), priority=2
        )
        send_event_mock.assert_called_with(message_created_payload)
        message_confirmation_payload = {
            "address": safe_address,
            "type": WebHookType.MESSAGE_CONFIRMATION.name,
            "messageHash": safe_message.message_hash,
            "chainId": str(EthereumNetwork.GANACHE.value),
        }
        # Create a confirmation should fire a signal and webhooks should be sended
        SafeMessageConfirmationFactory(safe_message=safe_message)
        webhook_task_mock.assert_called_with(
            args=(safe_address, message_confirmation_payload), priority=2
        )
        send_event_mock.assert_called_with(message_confirmation_payload)
