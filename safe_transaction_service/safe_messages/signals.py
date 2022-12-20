import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from safe_transaction_service.safe_messages.models import SafeMessage

from ..history.models import WebHookType
from ..history.tasks import send_webhook_task
from ..utils.ethereum import get_ethereum_network

logger = logging.getLogger(__name__)


@receiver(post_save, sender=SafeMessage)
def on_safe_message_save(sender):
    payload = {
        "address": sender.safe,
        "chainId": str(get_ethereum_network().value),
        "type": WebHookType.OFFCHAIN_MESSAGE_UPDATE.name,
    }
    send_webhook_task.apply_async(args=(sender.safe, payload), priority=2)
