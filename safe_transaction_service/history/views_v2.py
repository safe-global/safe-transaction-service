import logging

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from gnosis.eth.utils import fast_is_checksum_address

from safe_transaction_service.utils.utils import parse_boolean_query_param

from . import pagination, serializers
from .models import SafeContract
from .services.collectibles_service import CollectiblesServiceProvider
from .views import swagger_safe_balance_schema

logger = logging.getLogger(__name__)


class SafeCollectiblesView(GenericAPIView):
    serializer_class = serializers.SafeCollectibleResponseSerializer

    @swagger_safe_balance_schema(serializer_class)
    def get(self, request, address):
        """
        Get collectibles (ERC721 tokens) and information about them
        """
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )

        try:
            SafeContract.objects.get(address=address)
        except SafeContract.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        only_trusted = parse_boolean_query_param(
            self.request.query_params.get("trusted", False)
        )
        exclude_spam = parse_boolean_query_param(
            self.request.query_params.get("exclude_spam", False)
        )

        paginator = pagination.ListPagination(self.request)
        limit = paginator.limit
        offset = paginator.offset
        (
            safe_collectibles,
            count,
        ) = CollectiblesServiceProvider().get_collectibles_with_metadata_paginated(
            address, only_trusted, exclude_spam, limit, offset
        )
        paginator.set_count(count)
        serializer = self.get_serializer(safe_collectibles, many=True)
        return paginator.get_paginated_response(serializer.data)
