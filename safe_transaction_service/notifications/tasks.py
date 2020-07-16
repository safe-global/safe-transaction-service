from typing import Any, Dict, List, NoReturn, Optional, Tuple

import requests
from celery import app

from .clients.firebase_client import FirebaseProvider
from .models import FirebaseDevice


@app.shared_task()
def send_notification_task(address: Optional[str], payload: Dict[str, Any]) -> Tuple[int, int]:
    if not (address and payload):  # Both must be present
        return 0

    firebase_client = FirebaseProvider()
    firebase_devices = FirebaseDevice.objects.filter(address=address)  # TODO Use cache
    tokens = [firebase_device.cloud_messaging_token for firebase_device in firebase_devices]

    if not firebase_devices:
        return 0

    return firebase_client.send_message(tokens, payload)