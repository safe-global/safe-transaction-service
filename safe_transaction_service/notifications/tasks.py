from typing import Any, Dict, List, NoReturn, Optional, Tuple

import requests
from celery import app
from celery.utils.log import get_task_logger

from .clients.firebase_client import FirebaseProvider
from .models import FirebaseDevice

logger = get_task_logger(__name__)


@app.shared_task()
def send_notification_task(address: Optional[str], payload: Dict[str, Any]) -> Tuple[int, int]:
    if not (address and payload):  # Both must be present
        return 0

    firebase_client = FirebaseProvider()
    firebase_devices = FirebaseDevice.objects.filter(safe__address=address)  # TODO Use cache
    tokens = [firebase_device.cloud_messaging_token for firebase_device in firebase_devices]

    if not tokens:
        return 0

    success_count, failure_count, invalid_tokens = firebase_client.send_message(tokens, payload)
    if invalid_tokens:
        logger.info('Removing invalid tokens for safe=%s', address)
        FirebaseDevice.objects.filter(cloud_messaging_token__in=invalid_tokens).delete()

    return success_count, failure_count
