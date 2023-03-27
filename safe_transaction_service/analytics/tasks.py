import json

from django.db.models import Count, F, Q
from django.utils import timezone

from celery import app
from dateutil.relativedelta import relativedelta

from safe_transaction_service.analytics.services.analytics_service import (
    AnalyticsService,
)
from safe_transaction_service.history.models import MultisigTransaction
from safe_transaction_service.utils.redis import get_redis
from safe_transaction_service.utils.tasks import LOCK_TIMEOUT, SOFT_TIMEOUT


@app.shared_task(soft_time_limit=SOFT_TIMEOUT, time_limit=LOCK_TIMEOUT)
def get_transactions_per_safe_app_task():
    today = timezone.now()
    last_week = today - relativedelta(days=7)
    last_month = today - relativedelta(months=1)
    last_year = today - relativedelta(years=1)

    queryset = (
        MultisigTransaction.objects.filter(origin__name__isnull=False)
        .values(name=F("origin__name"), url=F("origin__url"))
        .annotate(
            total_tx=Count("origin__name"),
            tx_last_week=Count("origin__name", filter=Q(created__gt=last_week)),
            tx_last_month=Count("origin__name", filter=Q(created__gt=last_month)),
            tx_last_year=Count("origin__name", filter=Q(created__gt=last_year)),
        )
        .order_by("-total_tx")
    )

    if queryset:
        redis_key = AnalyticsService.REDIS_TRANSACTIONS_PER_SAFE_APP
        redis = get_redis()
        redis.set(redis_key, json.dumps(list(queryset)))
        return True
    return False
