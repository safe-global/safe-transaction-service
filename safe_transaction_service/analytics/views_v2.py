from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from safe_transaction_service.analytics.services.analytics_service import (
    get_analytics_service,
)


class AnalyticsMultisigTxsByOriginListView(ListAPIView):
    pagination_class = None
    swagger_schema = None
    renderer_classes = (JSONRenderer,)
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        analytics_service = get_analytics_service()
        return Response(analytics_service.get_safe_transactions_per_safe_app())
