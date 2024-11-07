import logging
from typing import List, Tuple

from django.db.models import Q

import django_filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListCreateAPIView
from rest_framework.response import Response
from safe_eth.eth.utils import fast_is_checksum_address

from safe_transaction_service.utils.utils import parse_boolean_query_param

from . import filters, pagination, serializers
from .models import SafeContract, SafeContractDelegate
from .services import BalanceServiceProvider
from .services.balance_service import Balance
from .services.collectibles_service import CollectiblesServiceProvider
from .views import swagger_assets_parameters

logger = logging.getLogger(__name__)


def swagger_pagination_parameters():
    """
    Pagination parameters are ignored with custom pagination

    :return: swagger pagination parameters
    """
    return [
        OpenApiParameter(
            "limit",
            location="query",
            type=OpenApiTypes.INT,
            description=pagination.ListPagination.limit_query_description,
        ),
        OpenApiParameter(
            "offset",
            location="query",
            type=OpenApiTypes.INT,
            description=pagination.ListPagination.offset_query_description,
        ),
    ]


@extend_schema(
    parameters=swagger_assets_parameters() + swagger_pagination_parameters(),
    responses={
        200: OpenApiResponse(
            response=serializers.SafeCollectibleResponseSerializer(many=True)
        ),
        404: OpenApiResponse(description="Safe not found"),
        422: OpenApiResponse(
            description="Safe address checksum not valid",
            response=serializers.CodeErrorResponse,
        ),
    },
)
class SafeCollectiblesView(GenericAPIView):
    serializer_class = serializers.SafeCollectibleResponseSerializer

    def get(self, request, address):
        """
        Get paginated collectibles (ERC721 tokens) and information about them of a given Safe account.
        The maximum limit allowed is 10.
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

        paginator = pagination.ListPagination(self.request, max_limit=10)
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


class DelegateListView(ListCreateAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.DelegateListFilter
    pagination_class = pagination.DefaultPagination
    queryset = SafeContractDelegate.objects.all()

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeDelegateResponseSerializer
        elif self.request.method == "POST":
            return serializers.DelegateSerializerV2

    @extend_schema(
        responses={
            200: serializers.SafeDelegateResponseSerializer,
            400: OpenApiResponse(description="Invalid data"),
        }
    )
    def get(self, request, **kwargs):
        """
        Returns a list with all the delegates
        """
        return super().get(request, **kwargs)

    @extend_schema(
        request=serializers.DelegateSerializerV2,
        responses={
            202: OpenApiResponse(description="Accepted"),
            400: OpenApiResponse(description="Malformed data"),
        },
    )
    def post(self, request, **kwargs):
        """
        Adds a new Safe delegate with a custom label. Calls with same delegate but different label or
        signer will update the label or delegator if a different one is provided.
        To generate the signature, the following EIP712 data hash needs to be signed:

        ```python
         {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "Delegate": [
                    {"name": "delegateAddress", "type": "address"},
                    {"name": "totp", "type": "uint256"},
                ],
            },
            "primaryType": "Delegate",
            "domain": {
                "name": "Safe Transaction Service",
                "version": "1.0",
                "chainId": chain_id,
            },
            "message": {
                "delegateAddress": delegate_address,
                "totp": totp,
            },
        }
        ```

        For the signature we use `TOTP` with `T0=0` and `Tx=3600`. `TOTP` is calculated by taking the
        Unix UTC epoch time (no milliseconds) and dividing by 3600 (natural division, no decimals).
        """
        return super().post(request, **kwargs)


class DelegateDeleteView(GenericAPIView):
    serializer_class = serializers.DelegateDeleteSerializerV2

    @extend_schema(
        request=serializer_class(),
        responses={
            204: OpenApiResponse(description="Deleted"),
            400: OpenApiResponse(description="Malformed data"),
            404: OpenApiResponse(description="Delegate not found"),
            422: OpenApiResponse(
                description="Invalid Ethereum address/Error processing data"
            ),
        },
    )
    def delete(self, request, delegate_address, *args, **kwargs):
        """
        Removes every delegate/delegator pair found associated with a given delegate address. The
        signature is built the same way as for adding a delegate, but in this case the signer can be
        either the `delegator` (owner) or the `delegate` itself. Check `POST /delegates/` to learn more.
        """
        if not fast_is_checksum_address(delegate_address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [delegate_address],
                },
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deleted, _ = SafeContractDelegate.objects.filter(
            Q(
                safe_contract_id=serializer.validated_data["safe"],
                delegate=delegate_address,
                delegator=serializer.validated_data["delegator"],
            )
            if serializer.validated_data.get("safe", None)
            else Q(
                delegate=delegate_address,
                delegator=serializer.validated_data["delegator"],
            )
        ).delete()
        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)


class SafeBalanceView(GenericAPIView):
    serializer_class = serializers.SafeBalanceResponseSerializer

    def get_parameters(self) -> Tuple[bool, bool]:
        """
        Parse query parameters:
        :return: Tuple with only_trusted, exclude_spam
        """
        only_trusted = parse_boolean_query_param(
            self.request.query_params.get("trusted", False)
        )
        exclude_spam = parse_boolean_query_param(
            self.request.query_params.get("exclude_spam", False)
        )
        return only_trusted, exclude_spam

    def get_result(self, *args, **kwargs) -> Tuple[List[Balance], int]:
        return BalanceServiceProvider().get_balances(*args, **kwargs)

    @extend_schema(
        parameters=swagger_assets_parameters() + swagger_pagination_parameters(),
        responses={
            200: OpenApiResponse(
                response=serializers.SafeCollectibleResponseSerializer(many=True)
            ),
            404: OpenApiResponse(description="Safe not found"),
            422: OpenApiResponse(
                description="Safe address checksum not valid",
                response=serializers.CodeErrorResponse,
            ),
        },
    )
    def get(self, request, address):
        """
        Get paginated balances for Ether and ERC20 tokens.
        The maximum limit allowed is 200.
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
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            only_trusted, exclude_spam = self.get_parameters()
            paginator = pagination.ListPagination(
                self.request, max_limit=200, default_limit=100
            )
            limit = paginator.limit
            offset = paginator.offset
            safe_balances, count = self.get_result(
                address,
                only_trusted=only_trusted,
                exclude_spam=exclude_spam,
                limit=limit,
                offset=offset,
            )
            paginator.set_count(count)
            serializer = self.get_serializer(safe_balances, many=True)
            return paginator.get_paginated_response(serializer.data)
