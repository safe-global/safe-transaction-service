from rest_framework.generics import ListAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from safe_transaction_service.analytics.services.analytics_service import (
    get_analytics_service,
)


class AnalyticsMultisigTxsByOriginListView(ListAPIView):
    pagination_class = None
    renderer_classes = (JSONRenderer,)
    serializer_class = None

    def get(self, request, format=None):
        analytics_service = get_analytics_service()
        return Response(analytics_service.get_safe_transactions_per_safe_app())
