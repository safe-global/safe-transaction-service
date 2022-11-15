import json

from rest_framework.generics import ListAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from safe_transaction_service.utils.redis import get_redis


class AnalyticsMultisigTxsByOriginListView(ListAPIView):
    pagination_class = None
    renderer_classes = (JSONRenderer,)
    serializer_class = None

    def get(self, request, format=None):
        redis_key = "analytics_transactions_per_safe_app"
        redis = get_redis()
        analytic_result = redis.get(redis_key)
        if analytic_result:
            return Response(json.loads(analytic_result))
        else:
            return Response([])
