from typing import Any, Dict

from celery import app

from safe_transaction_service.events.services.queue_service import QueueServiceProvider


@app.shared_task()
def send_event_to_queue_task(payload: Dict[str, Any]) -> bool:
    if payload:
        queue_service = QueueServiceProvider()
        return queue_service.send_event(payload)

    return False
