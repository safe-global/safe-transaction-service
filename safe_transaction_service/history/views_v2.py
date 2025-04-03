import hashlib
import logging
from typing import List, Optional, Tuple

from django.db.models import Q

import django_filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from eth_typing import ChecksumAddress, HexStr
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
)
from rest_framework.response import Response
from safe_eth.eth.utils import fast_is_checksum_address

from safe_transaction_service.utils.utils import parse_boolean_query_param

from ..loggers.custom_logger import http_request_log
from . import filters, pagination, serializers
from .cache import CacheSafeTxsView, cache_txs_view_for_address
from .models import MultisigTransaction, SafeContract, SafeContractDelegate
from .pagination import DummyPagination
from .services import BalanceServiceProvider, TransactionServiceProvider
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
        tags=["delegates"],
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


@extend_schema(
    tags=["transactions"],
)
class SafeMultisigTransactionDetailView(RetrieveAPIView):
    """
    Returns a multi-signature transaction given its Safe transaction hash
    """

    serializer_class = serializers.SafeMultisigTransactionResponseSerializerV2
    lookup_field = "safe_tx_hash"
    lookup_url_kwarg = "safe_tx_hash"

    def get_queryset(self):
        return (
            MultisigTransaction.objects.with_confirmations_required()
            .prefetch_related("confirmations")
            .select_related("ethereum_tx__block")
        )

    def delete(self, request, safe_tx_hash: HexStr):
        """
        Removes the queued but not executed multi-signature transaction associated with the given Safe transaction hash.
        Only the proposer or the delegate who proposed the transaction can delete it.
        If the transaction was proposed by a delegate, it must still be a valid delegate for the transaction proposer.
        An EOA is required to sign the following EIP-712 data:

        ```python
         {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "DeleteRequest": [
                    {"name": "safeTxHash", "type": "bytes32"},
                    {"name": "totp", "type": "uint256"},
                ],
            },
            "primaryType": "DeleteRequest",
            "domain": {
                "name": "Safe Transaction Service",
                "version": "1.0",
                "chainId": chain_id,
                "verifyingContract": safe_address,
            },
            "message": {
                "safeTxHash": safe_tx_hash,
                "totp": totp,
            },
        }
        ```

        `totp` parameter is calculated with `T0=0` and `Tx=3600`. `totp` is calculated by taking the
        Unix UTC epoch time (no milliseconds) and dividing by 3600 (natural division, no decimals)
        """
        request.data["safe_tx_hash"] = safe_tx_hash
        serializer = serializers.SafeMultisigTransactionDeleteSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)
        MultisigTransaction.objects.filter(safe_tx_hash=safe_tx_hash).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SafeMultisigTransactionListView(ListAPIView):
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    )
    filterset_class = filters.MultisigTransactionFilter
    ordering_fields = ["nonce", "created", "modified"]
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Just for openApi doc purposes
            return MultisigTransaction.objects.none()
        return (
            MultisigTransaction.objects.filter(safe=self.kwargs["address"])
            .with_confirmations_required()
            .prefetch_related("confirmations")
            .select_related("ethereum_tx__block")
            .order_by("-nonce", "-created")
        )

    def get_unique_nonce(self, address: str):
        """
        :param address:
        :return: Number of Multisig Transactions with different nonce
        """
        only_trusted = parse_boolean_query_param(
            self.request.query_params.get("trusted", True)
        )
        queryset = MultisigTransaction.objects.filter(safe=address)
        if only_trusted:
            queryset = queryset.filter(trusted=True)
        return queryset.distinct("nonce").count()

    def get_serializer_class(self):
        """
        Proxy returning a serializer class according to the request's verb.
        """
        if self.request.method == "GET":
            return serializers.SafeMultisigTransactionResponseSerializerV2
        elif self.request.method == "POST":
            return serializers.SafeMultisigTransactionSerializer

    @extend_schema(
        tags=["transactions"],
        responses={
            200: OpenApiResponse(
                response=serializers.SafeMultisigTransactionResponseSerializerV2
            ),
            400: OpenApiResponse(description="Invalid data"),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Invalid ethereum address",
            ),
        },
    )
    @cache_txs_view_for_address(
        cache_tag=CacheSafeTxsView.LIST_MULTISIGTRANSACTIONS_VIEW_CACHE_KEY
    )
    def get(self, request, *args, **kwargs):
        """
        Returns all the multi-signature transactions for a given Safe address.
        By default, only ``trusted`` multisig transactions are returned.
        """
        address = kwargs["address"]
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )

        response = super().get(request, *args, **kwargs)
        response.data["count_unique_nonce"] = self.get_unique_nonce(address)
        return response

    @extend_schema(
        tags=["transactions"],
        request=serializers.SafeMultisigTransactionSerializer,
        responses={
            201: OpenApiResponse(
                description="Created or signature updated",
            ),
            400: OpenApiResponse(description="Invalid data"),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Invalid ethereum address | User is not an owner | Invalid safeTxHash |"
                "Invalid signature | Nonce already executed | Sender is not an owner",
            ),
        },
    )
    def post(self, request, address, format=None):
        """
        Creates a multi-signature transaction for a given Safe account with its confirmations and
        retrieves all the information related.
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

        request.data["safe"] = address
        serializer = self.get_serializer(data=request.data)
        logger.info(
            "Creating MultisigTransaction",
            extra={"http_request": http_request_log(request, log_data=True)},
        )
        if not serializer.is_valid():
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors
            )
        else:
            serializer.save()
            return Response(status=status.HTTP_201_CREATED)


class AllTransactionsListView(ListAPIView):
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    )
    ordering_fields = ["timestamp"]
    allowed_ordering_fields = ordering_fields + [
        f"-{ordering_field}" for ordering_field in ordering_fields
    ]
    pagination_class = pagination.SmallPagination
    serializer_class = (
        serializers.AllTransactionsSchemaSerializerV2
    )  # Just for docs, not used

    def get_ordering_parameter(self) -> Optional[str]:
        return self.request.query_params.get(OrderingFilter.ordering_param)

    def get_page_tx_identifiers(
        self,
        safe: ChecksumAddress,
        ordering: Optional[str],
        limit: int,
        offset: int,
    ) -> Optional[Response]:
        """
        This query will merge txs and events and will return the important
        identifiers (``safeTxHash`` or ``txHash``) filtered

        :param safe:
        :param ordering:
        :param limit:
        :param offset:
        :return: Return tx identifiers paginated
        """
        transaction_service = TransactionServiceProvider()

        logger.debug(
            "%s: Getting all tx identifiers for Safe=%s ordering=%s limit=%d offset=%d",
            self.__class__.__name__,
            safe,
            ordering,
            limit,
            offset,
        )
        queryset = self.filter_queryset(
            transaction_service.get_all_tx_identifiers(safe)
        )
        page = self.paginate_queryset(queryset)
        logger.debug(
            "%s: Got all tx identifiers for Safe=%s ordering=%s limit=%d offset=%d",
            self.__class__.__name__,
            safe,
            ordering,
            limit,
            offset,
        )

        return page

    def list(self, request, *args, **kwargs):
        transaction_service = TransactionServiceProvider()
        safe = self.kwargs["address"]
        ordering = self.get_ordering_parameter()
        # Trick to get limit and offset
        list_pagination = DummyPagination(self.request)
        limit, offset = list_pagination.limit, list_pagination.offset

        tx_identifiers_page = self.get_page_tx_identifiers(
            safe, ordering, limit, offset
        )
        if not tx_identifiers_page:
            return self.get_paginated_response([])

        all_tx_identifiers = [element.ethereum_tx_id for element in tx_identifiers_page]
        all_txs = transaction_service.get_all_txs_from_identifiers(
            safe, all_tx_identifiers
        )
        logger.debug(
            "%s: Got all txs from identifiers for Safe=%s",
            self.__class__.__name__,
            safe,
        )
        all_txs_serialized = transaction_service.serialize_all_txs_v2(all_txs)
        logger.debug(
            "%s: All txs from identifiers for Safe=%s were serialized",
            self.__class__.__name__,
            safe,
        )
        paginated_response = self.get_paginated_response(all_txs_serialized)
        logger.debug(
            "%s: All txs from identifiers for Safe=%s: %s",
            self.__class__.__name__,
            safe,
            paginated_response.data["results"],
        )
        return paginated_response

    @extend_schema(tags=["transactions"])
    def get(self, request, *args, **kwargs):
        """
        Returns all the *executed* transactions for a given Safe address.
        The list has different structures depending on the transaction type:
        - Multisig Transactions for a Safe. `tx_type=MULTISIG_TRANSACTION`.
        - Module Transactions for a Safe. `tx_type=MODULE_TRANSACTION`
        - Incoming Transfers of Ether/ERC20 Tokens/ERC721 Tokens. `tx_type=ETHEREUM_TRANSACTION`
        Ordering_fields: ["timestamp"] eg: `-timestamp` (default one) or `timestamp`

        Note: This endpoint has a bug that will be fixed in next versions of the endpoint. Pagination is done
        using the `Transaction Hash`, and due to that the number of relevant transactions with the same
        `Transaction Hash` cannot be known beforehand. So if there are only 2 transactions
        with the same `Transaction Hash`, `count` of the endpoint will be 1
        but there will be 2 transactions in the list.
        """
        address = kwargs["address"]
        if not fast_is_checksum_address(address):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address],
                },
            )
        ordering = self.get_ordering_parameter()
        if ordering and ordering not in self.allowed_ordering_fields:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "code": 1,
                    "message": f"Ordering field is not valid, only f{self.allowed_ordering_fields} are allowed",
                    "arguments": [ordering],
                },
            )

        response = super().get(request, *args, **kwargs)
        response.setdefault(
            "ETag",
            "W/" + hashlib.md5(str(response.data["results"]).encode()).hexdigest(),
        )
        return response
