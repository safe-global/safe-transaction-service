import json

from django.db.models import Count, F

from celery import app

from safe_transaction_service.history.models import MultisigTransaction
from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.tasks import LOCK_TIMEOUT, SOFT_TIMEOUT


@app.shared_task(soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def get_transactions_per_safe_app_task():
    queryset = (
        MultisigTransaction.objects.filter(origin__name__isnull=False)
        .values(name=F("origin__name"), url=F("origin__url"))
        .annotate(transactions=Count("name"))
        .order_by("-transactions")
    )

    if queryset:
        redis_key = "analytics_transactions_per_safe_app"
        redis = get_redis()
        redis.set(redis_key, json.dumps(list(queryset)))
