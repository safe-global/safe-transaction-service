import json
from functools import cache
from typing import List

from safe_transaction_service.utils.redis import get_redis


@cache
def get_analytics_service() -> "AnalyticsService":
    return AnalyticsService()


class AnalyticsService:
    REDIS_TRANSACTIONS_PER_SAFE_APP = "analytics_transactions_per_safe_app"

    def get_safe_transactions_per_safe_app(self) -> List:
        redis = get_redis()
        analytic_result = redis.get(self.REDIS_TRANSACTIONS_PER_SAFE_APP)
        if analytic_result:
            return json.loads(analytic_result)
        else:
            return []
