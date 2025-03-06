import hashlib
import logging
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from eth_typing import ChecksumAddress, HexStr
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import (
    DestroyAPIView,
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    get_object_or_404,
)
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from safe_eth.eth import EthereumClient, EthereumNetwork, get_auto_ethereum_client
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.utils import fast_is_checksum_address
from safe_eth.safe import CannotEstimateGas
from safe_eth.safe.safe_deployments import safe_deployments

from safe_transaction_service import __version__
from safe_transaction_service.utils.ethereum import get_chain_id
from safe_transaction_service.utils.utils import parse_boolean_query_param

from ..loggers.custom_logger import http_request_log
from . import filters, pagination, serializers
from .cache import CacheSafeTxsView, cache_txs_view_for_address
from .exceptions import CannotGetSafeInfoFromBlockchain
from .helpers import add_tokens_to_transfers, is_valid_unique_transfer_id
from .models import (
    ERC20Transfer,
    ERC721Transfer,
    InternalTx,
    ModuleTransaction,
    MultisigConfirmation,
    MultisigTransaction,
    SafeContract,
    SafeContractDelegate,
    SafeLastStatus,
    SafeMasterCopy,
    TransferDict,
)
from .pagination import DummyPagination
from .serializers import get_data_decoded_from_data
from .services import (
    BalanceServiceProvider,
    IndexServiceProvider,
    SafeServiceProvider,
    TransactionServiceProvider,
)

logger = logging.getLogger(__name__)


class AboutView(APIView):
    """
    Returns information and configuration of the service
    """

    renderer_classes = (JSONRenderer,)
    logger = logging.getLogger("AboutView")

    def get(self, request, format=None):
        self.logger.info("From about")
        content = {
            "name": "Safe Transaction Service",
            "version": __version__,
            "api_version": request.version,
            "secure": request.is_secure(),
            "host": request.get_host(),
            "headers": [x for x in request.META.keys() if "FORWARD" in x],
            "settings": {
                "AWS_CONFIGURED": settings.AWS_CONFIGURED,
                "AWS_S3_PUBLIC_URL": settings.AWS_S3_PUBLIC_URL,
                "ETHEREUM_NODE_URL": settings.ETHEREUM_NODE_URL,
                "ETHEREUM_TRACING_NODE_URL": settings.ETHEREUM_TRACING_NODE_URL,
                "ETH_EVENTS_BLOCK_PROCESS_LIMIT": settings.ETH_EVENTS_BLOCK_PROCESS_LIMIT,
                "ETH_EVENTS_BLOCK_PROCESS_LIMIT_MAX": settings.ETH_EVENTS_BLOCK_PROCESS_LIMIT_MAX,
                "ETH_EVENTS_QUERY_CHUNK_SIZE": settings.ETH_EVENTS_QUERY_CHUNK_SIZE,
                "ETH_EVENTS_UPDATED_BLOCK_BEHIND": settings.ETH_EVENTS_UPDATED_BLOCK_BEHIND,
                "ETH_INTERNAL_NO_FILTER": settings.ETH_INTERNAL_NO_FILTER,
                "ETH_INTERNAL_TRACE_TXS_BATCH_SIZE": settings.ETH_INTERNAL_TRACE_TXS_BATCH_SIZE,
                "ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT": settings.ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT,
                "ETH_L2_NETWORK": settings.ETH_L2_NETWORK,
                "ETH_REORG_BLOCKS": settings.ETH_REORG_BLOCKS,
                "SSO_ENABLED": settings.SSO_ENABLED,
                "TOKENS_LOGO_BASE_URI": settings.TOKENS_LOGO_BASE_URI,
                "TOKENS_LOGO_EXTENSION": settings.TOKENS_LOGO_EXTENSION,
            },
        }

        return Response(content)


class AboutEthereumRPCView(APIView):
    """
    Returns information about ethereum RPC the service is using
    """

    renderer_classes = (JSONRenderer,)

    def _get_info(self, ethereum_client: EthereumClient) -> Dict[str, Any]:
        try:
            client_version = ethereum_client.w3.client_version
        except (IOError, ValueError):
            client_version = "Error getting client version"

        try:
            syncing = ethereum_client.w3.eth.syncing
        except (IOError, ValueError):
            syncing = "Error getting syncing status"

        ethereum_chain_id = get_chain_id()
        ethereum_network = EthereumNetwork(ethereum_chain_id)
        return {
            "version": client_version,
            "block_number": ethereum_client.current_block_number,
            "chain_id": ethereum_chain_id,
            "chain": ethereum_network.name,
            "syncing": syncing,
        }

    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, format=None):
        """
        Get information about the Ethereum RPC node used by the service
        """
        ethereum_client = get_auto_ethereum_client()
        return Response(self._get_info(ethereum_client))


class AboutEthereumTracingRPCView(AboutEthereumRPCView):
    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, format=None):
        """
        Get information about the Ethereum Tracing RPC node used by the service (if any configured)
        """
        if not settings.ETHEREUM_TRACING_NODE_URL:
            return Response(status=status.HTTP_404_NOT_FOUND)
        else:
            ethereum_client = EthereumClient(settings.ETHEREUM_TRACING_NODE_URL)
            return Response(self._get_info(ethereum_client))


@extend_schema(responses={200: serializers.IndexingStatusSerializer})
class IndexingView(GenericAPIView):
    serializer_class = serializers.IndexingStatusSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request):
        """
        Get current indexing status for ERC20/721 events
        """
        index_service = IndexServiceProvider()

        serializer = self.get_serializer(index_service.get_indexing_status())
        return Response(status=status.HTTP_200_OK, data=serializer.data)


@extend_schema(responses={200: serializers.MasterCopyResponseSerializer})
class SingletonsView(ListAPIView):
    """
    Returns a list of Master Copies configured in the service
    """

    serializer_class = serializers.MasterCopyResponseSerializer
    pagination_class = None

    def get_queryset(self):
        return SafeMasterCopy.objects.relevant()


@extend_schema(
    responses={
        200: serializers.SafeDeploymentSerializer,
        404: OpenApiResponse(description="Provided version does not exist"),
    },
    parameters=[
        OpenApiParameter(
            "version",
            OpenApiTypes.STR,
            default=None,
            description="Filter by Safe version",
        ),
        OpenApiParameter(
            "contract",
            OpenApiTypes.STR,
            default=None,
            description="Filter by Safe contract name",
        ),
    ],
)
class SafeDeploymentsView(ListAPIView):
    """
    Returns a list of safe deployments by version
    """

    serializer_class = serializers.SafeDeploymentSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @method_decorator(cache_page(60))  # 60 seconds
    def get(self, request):
        filter_version = self.request.query_params.get("version")
        filter_contract = self.request.query_params.get("contract")

        if filter_version and filter_version not in safe_deployments.keys():
            return Response(status=status.HTTP_404_NOT_FOUND)

        versions = [filter_version] if filter_version else list(safe_deployments.keys())
        chain_id = str(get_chain_id())
        data_response = []
        for version in versions:
            contracts = []
            if filter_contract:
                # Filter by contract name
                if addresses := safe_deployments[version].get(filter_contract):
                    for address in addresses.get(chain_id, []):
                        contracts.append(
                            {
                                "contract_name": filter_contract,
                                "address": address,
                            }
                        )
            else:
                for contract_name, addresses in safe_deployments[version].items():
                    for address in addresses.get(chain_id, []):
                        contracts.append(
                            {
                                "contract_name": contract_name,
                                "address": address,
                            }
                        )

            data_response.append({"version": version, "contracts": contracts})

        serializer = self.serializer_class(data=data_response, many=True)
        serializer.is_valid(raise_exception=True)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


@extend_schema(
    tags=["transactions"],
    responses={
        200: OpenApiResponse(
            response=serializers.AllTransactionsSchemaSerializer,
            description="A list with every element with the structure of one of these transaction"
            "types",
        ),
        422: OpenApiResponse(
            response=serializers.CodeErrorResponse,
            description="Checksum address validation failed",
        ),
        400: OpenApiResponse(
            response=serializers.CodeErrorResponse,
            description="Ordering field is not valid",
        ),
    },
)
@extend_schema(deprecated=True)
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
        serializers.AllTransactionsSchemaSerializer
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
        all_txs_serialized = transaction_service.serialize_all_txs(all_txs)
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


@extend_schema(
    tags=["transactions"],
    responses={
        200: serializers.SafeModuleTransactionResponseSerializer,
        404: OpenApiResponse(description="ModuleTransaction does not exist"),
        400: OpenApiResponse(
            response=serializers.CodeErrorResponse,
            description="Invalid moduleTransactionId",
        ),
    },
)
class SafeModuleTransactionView(RetrieveAPIView):
    serializer_class = serializers.SafeModuleTransactionResponseSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @method_decorator(cache_page(60 * 60))  # 1 hour
    def get(self, request, module_transaction_id: str, *args, **kwargs) -> Response:
        """
        Returns a transaction executed from a module given its associated module transaction ID
        """
        if module_transaction_id and not is_valid_unique_transfer_id(
            module_transaction_id
        ):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "code": 1,
                    "message": "module_transaction_id is not valid",
                    "arguments": [module_transaction_id],
                },
            )
        tx_hash = module_transaction_id[1:65]
        trace_address = module_transaction_id[65:]
        try:
            module_transaction = ModuleTransaction.objects.get(
                internal_tx__ethereum_tx_id=tx_hash,
                internal_tx__trace_address=trace_address,
            )
            serializer = self.get_serializer(module_transaction)
            return Response(status=status.HTTP_200_OK, data=serializer.data)
        except ModuleTransaction.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    tags=["transactions"],
    responses={
        200: serializers.SafeModuleTransactionResponseSerializer,
        422: OpenApiResponse(
            response=serializers.CodeErrorResponse,
            description="Checksum address validation failed",
        ),
    },
)
class SafeModuleTransactionListView(ListAPIView):
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    )
    filterset_class = filters.ModuleTransactionFilter
    ordering_fields = ["created"]
    pagination_class = pagination.DefaultPagination
    serializer_class = serializers.SafeModuleTransactionResponseSerializer

    def get_queryset(self):
        # Just for swagger doc
        if getattr(self, "swagger_fake_view", False):
            return ModuleTransaction.objects.none()

        return (
            ModuleTransaction.objects.filter(safe=self.kwargs["address"])
            .select_related("internal_tx__ethereum_tx")
            .order_by("-created")
        )

    @cache_txs_view_for_address(
        cache_tag=CacheSafeTxsView.LIST_MODULETRANSACTIONS_VIEW_CACHE_KEY
    )
    def get(self, request, address, format=None):
        """
        Returns all the transactions executed from modules given a Safe address
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

        return super().get(request, address)


class SafeMultisigConfirmationsView(ListCreateAPIView):
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        return MultisigConfirmation.objects.filter(
            multisig_transaction_id=self.kwargs["safe_tx_hash"]
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["safe_tx_hash"] = self.kwargs.get("safe_tx_hash")
        return context

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeMultisigConfirmationResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeMultisigConfirmationSerializer

    @extend_schema(
        tags=["transactions"],
        responses={
            200: serializers.SafeMultisigConfirmationResponseSerializer,
            400: OpenApiResponse(description="Invalid data"),
        },
    )
    def get(self, request, *args, **kwargs):
        """
        Returns the list of confirmations for the multi-signature transaction associated with
        the given Safe transaction hash
        """
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["transactions"],
        responses={
            201: OpenApiResponse(description="Created"),
            400: OpenApiResponse(description="Malformed data"),
            422: OpenApiResponse(description="Error processing data"),
        },
    )
    def post(self, request, *args, **kwargs):
        """
        Adds a new confirmation to the pending multi-signature transaction associated with the
        given Safe transaction hash. Multiple signatures can be submitted at once. This endpoint
        does not support the use of delegates to make transactions trusted.
        """
        logger.info(
            "Creating MultisigConfirmation",
            extra={"http_request": http_request_log(request, log_data=True)},
        )
        return super().post(request, *args, **kwargs)


@extend_schema_view(
    get=extend_schema(tags=["transactions"]),
    delete=extend_schema(
        tags=["transactions"],
        request=serializers.SafeMultisigTransactionDeleteSerializer,
        responses={
            204: OpenApiResponse(description="Deleted"),
            404: OpenApiResponse(description="Transaction not found"),
            400: OpenApiResponse(description="Error processing data"),
        },
    ),
)
@extend_schema(
    deprecated=True,
)
class SafeMultisigTransactionDetailView(RetrieveAPIView):
    """
    Returns a multi-signature transaction given its Safe transaction hash
    """

    serializer_class = serializers.SafeMultisigTransactionResponseSerializer
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
            return serializers.SafeMultisigTransactionResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeMultisigTransactionSerializer

    @extend_schema(
        deprecated=True,
        tags=["transactions"],
        responses={
            200: OpenApiResponse(
                response=serializers.SafeMultisigTransactionResponseSerializer
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
        deprecated=True,
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


def swagger_assets_parameters():
    """
    Return the swagger doc of ERC20, ERC721 default filters
    Used for documentation purposes

    :return:
    """
    return [
        OpenApiParameter(
            "trusted",
            location="query",
            type=OpenApiTypes.BOOL,
            default=False,
            description="If `True` just trusted tokens will be returned",
        ),
        OpenApiParameter(
            "exclude_spam",
            location="query",
            type=OpenApiTypes.BOOL,
            default=False,
            description="If `True` spam tokens will not be returned",
        ),
    ]


class SafeBalanceView(GenericAPIView):
    serializer_class = serializers.SafeBalanceResponseSerializer
    pagination_class = None  # Don't show limit/offset in swagger

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

    def get_result(self, *args, **kwargs):
        return BalanceServiceProvider().get_balances(*args, **kwargs)

    @extend_schema(
        parameters=swagger_assets_parameters(),
        responses={
            200: OpenApiResponse(
                response=serializers.SafeBalanceResponseSerializer(many=True)
            ),
            404: OpenApiResponse(description="Safe not found"),
            422: OpenApiResponse(description="Safe address checksum not valid"),
        },
        deprecated=False,
    )
    def get(self, request, address):
        """
        Get balance for Ether and ERC20 tokens of a given Safe account
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
            safe_balances, _ = self.get_result(
                address, only_trusted=only_trusted, exclude_spam=exclude_spam
            )
            serializer = self.get_serializer(safe_balances, many=True)
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class TransferView(RetrieveAPIView):
    serializer_class = serializers.TransferWithTokenInfoResponseSerializer
    pagination_class = None

    def get_erc20_erc721_transfer(
        self, transaction_hash: HexStr, log_index: int
    ) -> TransferDict:
        """
        Search ERCTransfer by transaction_hash and log_index event.

        :param transaction_hash: ethereum transaction hash
        :param log_index: event log index
        :return: transfer
        """
        erc20_queryset = self.filter_queryset(
            ERC20Transfer.objects.filter(
                ethereum_tx=transaction_hash, log_index=log_index
            ).token_txs()
        )
        erc721_queryset = self.filter_queryset(
            ERC721Transfer.objects.filter(
                ethereum_tx=transaction_hash, log_index=log_index
            ).token_txs()
        )
        return ERC20Transfer.objects.token_transfer_values(
            erc20_queryset, erc721_queryset
        )

    def get_ethereum_transfer(
        self, transaction_hash: HexStr, trace_address: str
    ) -> TransferDict:
        """
        Search an ethereum transfer by transaction hash and trace address

        :param transaction_hash: ethereum transaction hash
        :param trace_address: ethereum trace address
        :return: transfer
        """
        ether_queryset = self.filter_queryset(
            InternalTx.objects.ether_txs().filter(
                ethereum_tx=transaction_hash, trace_address=trace_address
            )
        )
        return InternalTx.objects.ether_txs_values(ether_queryset)

    def get_queryset(self, transfer_id: str) -> TransferDict:
        # transfer_id is composed by transfer_type (ethereum transfer or token_transfer) + tx_hash + (log_index or trace_address)
        transfer_type = transfer_id[0]
        tx_hash = transfer_id[1:65]
        if transfer_type == "i":
            # It is an ethereumTransfer
            trace_address = transfer_id[65:]
            return self.get_ethereum_transfer(tx_hash, trace_address)
        else:
            # It is an tokenTransfer
            log_index = int(transfer_id[65:])
            return self.get_erc20_erc721_transfer(tx_hash, log_index)

    @extend_schema(
        tags=["transactions"],
        responses={
            200: OpenApiResponse(
                response=serializers.TransferWithTokenInfoResponseSerializer
            ),
            404: OpenApiResponse(description="Transfer does not exist"),
            400: OpenApiResponse(description="Invalid transferId"),
        },
    )
    @method_decorator(cache_page(60 * 60))  # 1 hour
    def get(self, request, transfer_id: str, *args, **kwargs) -> Response:
        """
        Returns a token transfer associated with the given transfer ID
        """

        if transfer_id and not is_valid_unique_transfer_id(transfer_id):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "code": 1,
                    "message": "transfer_id is not valid",
                    "arguments": [transfer_id],
                },
            )
        transfer = self.get_queryset(transfer_id)
        if len(transfer) == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(add_tokens_to_transfers(transfer)[0])
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeTransferListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.TransferListFilter
    serializer_class = serializers.TransferWithTokenInfoResponseSerializer
    pagination_class = pagination.DefaultPagination

    def get_transfers(self, address: str):
        erc20_queryset = self.filter_queryset(
            ERC20Transfer.objects.to_or_from(address).token_txs()
        )[: settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS]
        erc721_queryset = self.filter_queryset(
            ERC721Transfer.objects.to_or_from(address).token_txs()
        )[: settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS]
        ether_queryset = self.filter_queryset(
            InternalTx.objects.ether_txs_for_address(address)
        )[: settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS]
        return InternalTx.objects.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Just for openApi doc purposes
            return InternalTx.objects.none()
        address = self.kwargs["address"]
        return self.get_transfers(address)

    def list(self, request, *args, **kwargs):
        # Queryset must be already filtered, as we cannot filter a union
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(add_tokens_to_transfers(page), many=True)
            return self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(
                add_tokens_to_transfers(queryset), many=True
            )
            return Response(serializer.data)

    @extend_schema(
        tags=["transactions"],
        responses={
            200: serializers.TransferWithTokenInfoResponseSerializer(many=True),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Safe address checksum not valid",
            ),
        },
    )
    @cache_txs_view_for_address(CacheSafeTxsView.LIST_TRANSFERS_VIEW_CACHE_KEY)
    def get(self, request, address, format=None):
        """
        Returns the list of token transfers for a given Safe address.
        Only 1000 newest transfers will be returned.
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

        return super().get(request, address)


class SafeIncomingTransferListView(SafeTransferListView):

    @extend_schema(
        tags=["transactions"],
        responses={
            200: serializers.TransferWithTokenInfoResponseSerializer(many=True),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Safe address checksum not valid",
            ),
        },
    )
    def get(self, *args, **kwargs):
        """
        Returns incoming ether/tokens transfers for a Safe.
        Only 1000 newest transfers will be returned.
        """
        return super().get(*args, **kwargs)

    def get_transfers(self, address: str):
        erc20_queryset = self.filter_queryset(
            ERC20Transfer.objects.incoming(address).token_txs()
        )[: settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS]
        erc721_queryset = self.filter_queryset(
            ERC721Transfer.objects.incoming(address).token_txs()
        )[: settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS]
        ether_queryset = self.filter_queryset(
            InternalTx.objects.ether_incoming_txs_for_address(address)
        )[: settings.TX_SERVICE_ALL_TXS_ENDPOINT_LIMIT_TRANSFERS]

        return InternalTx.objects.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )


class SafeCreationView(GenericAPIView):
    serializer_class = serializers.SafeCreationInfoResponseSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @extend_schema(
        responses={
            200: serializer_class(),
            404: OpenApiResponse(description="Safe creation not found"),
            422: OpenApiResponse(description="Owner address checksum not valid"),
            503: OpenApiResponse(description="Problem connecting to Ethereum network"),
        }
    )
    @method_decorator(cache_page(60 * 60))  # 1 hour
    def get(self, request, address, *args, **kwargs):
        """
        Returns detailed information on the Safe creation transaction of a given Safe.

        Note: When event indexing is being used and multiple Safes are deployed in the same transaction
        the result might not be accurate due to the indexer not knowing which events belong to which Safe
        deployment.
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

        safe_creation_info = SafeServiceProvider().get_safe_creation_info(address)
        if not safe_creation_info:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(safe_creation_info)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeInfoView(GenericAPIView):
    serializer_class = serializers.SafeInfoResponseSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @extend_schema(
        responses={
            200: serializer_class(),
            404: OpenApiResponse(description="Safe not found"),
            422: OpenApiResponse(
                description="code = 1: Checksum address validation failed\ncode = 50: Cannot get Safe info"
            ),
        }
    )
    def get(self, request, address, *args, **kwargs):
        """
        Returns detailed information of a given Safe account
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

        if not SafeContract.objects.filter(address=address).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            # safe_info = SafeServiceProvider().get_safe_info(address)
            safe_info = SafeServiceProvider().get_safe_info_from_blockchain(address)
            serializer = self.get_serializer(safe_info)
            return Response(status=status.HTTP_200_OK, data=serializer.data)
        except CannotGetSafeInfoFromBlockchain:
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 50,
                    "message": "Cannot get Safe info from blockchain",
                    "arguments": [address],
                },
            )


class ModulesView(GenericAPIView):
    serializer_class = serializers.ModulesResponseSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @extend_schema(
        responses={
            200: serializers.ModulesResponseSerializer(),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Module address checksum not valid",
            ),
        }
    )
    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, address, *args, **kwargs):
        """
        Returns the list of Safes that have the provided module enabled
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

        safes_for_module = SafeLastStatus.objects.addresses_for_module(address)
        serializer = self.get_serializer(data={"safes": safes_for_module})
        assert serializer.is_valid()
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class OwnersView(GenericAPIView):
    serializer_class = serializers.OwnerResponseSerializer
    pagination_class = None  # Don't show limit/offset in swagger

    @extend_schema(
        responses={
            200: serializers.OwnerResponseSerializer(),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Owner address checksum not valid",
            ),
        }
    )
    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, address, *args, **kwargs):
        """
        Returns the list of Safe accounts that have the given address as their owner
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

        safes_for_owner = SafeLastStatus.objects.addresses_for_owner(address)
        serializer = self.get_serializer(data={"safes": safes_for_owner})
        assert serializer.is_valid()
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class DataDecoderView(GenericAPIView):
    serializer_class = serializers.DataDecoderSerializer

    @extend_schema(
        responses={
            200: OpenApiResponse(
                description="Decoded data", response=serializers.DataDecoderSerializer
            ),
            404: OpenApiResponse(
                description="Cannot find function selector to decode data"
            ),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse, description="Invalid data"
            ),
        }
    )
    def post(self, request, format=None):
        """
        Returns the decoded data using the Safe Transaction Service internal ABI information given
        the transaction data as a `0x` prefixed hexadecimal string.
        If the address of the receiving contract is provided, the decoded data will be more accurate,
        as in case of an ABI collision the Safe Transaction Service would know which ABI to use.
        """

        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors
            )
        else:
            data_decoded = get_data_decoded_from_data(
                serializer.data["data"], address=serializer.data["to"]
            )
            if data_decoded:
                return Response(status=status.HTTP_200_OK, data=data_decoded)
            else:
                return Response(status=status.HTTP_404_NOT_FOUND, data=data_decoded)


class SafeMultisigTransactionEstimateView(GenericAPIView):
    serializer_class = serializers.SafeMultisigTransactionEstimateSerializer
    response_serializer = serializers.SafeMultisigTransactionEstimateResponseSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            # Just for schema generation metadata
            context["safe_address"] = NULL_ADDRESS
        else:
            context["safe_address"] = self.kwargs["address"]
        return context

    @extend_schema(
        tags=["transactions"],
        responses={
            200: response_serializer,
            400: OpenApiResponse(description="Data not valid"),
            404: OpenApiResponse(description="Safe not found"),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse, description="Tx not valid"
            ),
        },
    )
    def post(self, request, address, *args, **kwargs):
        """
        Returns the estimated `safeTxGas` for a given Safe address and multi-signature transaction.
        Estimation is disabled for L2 networks, as this is only required for Safes with version < 1.3.0
        and those versions are not supported in L2 networks.
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

        if not SafeContract.objects.filter(address=address).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        # This endpoint is only needed for Safes < 1.3.0, so it should be disabled for L2 chains as they
        # don't support Safes below that version
        if settings.ETH_L2_NETWORK:
            response_serializer = self.response_serializer(data={"safe_tx_gas": 0})
            response_serializer.is_valid()
            return Response(status=status.HTTP_200_OK, data=response_serializer.data)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            try:
                response_serializer = self.response_serializer(data=serializer.save())
                response_serializer.is_valid(raise_exception=True)
                return Response(
                    status=status.HTTP_200_OK, data=response_serializer.data
                )
            except CannotEstimateGas as exc:
                logger.warning(
                    "Cannot estimate gas for safe=%s data=%s",
                    address,
                    serializer.validated_data,
                )
                return Response(
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    data={
                        "code": 30,
                        "message": "Gas estimation failed",
                        "arguments": [str(exc)],
                    },
                )
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)


# Deprecated ---------------------------------------------------------------


class DelegateListView(ListCreateAPIView):
    """

    .. deprecated:: 4.38.0
       Deprecated in favor of V2 view supporting EIP712 signatures
    """

    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.DelegateListFilter
    pagination_class = pagination.DefaultPagination
    queryset = SafeContractDelegate.objects.all()

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeDelegateResponseSerializer
        elif self.request.method == "POST":
            return serializers.DelegateSerializer

    @extend_schema(
        deprecated=True, responses={400: OpenApiResponse(description="Invalid data")}
    )
    def get(self, request, **kwargs):
        """
        Returns a list with all the delegates
        """
        return super().get(request, **kwargs)

    @extend_schema(
        deprecated=True,
        responses={
            202: OpenApiResponse(description="Accepted"),
            400: OpenApiResponse(description="Malformed data"),
        },
    )
    def post(self, request, **kwargs):
        """
        Adds a new Safe delegate with a custom label. Calls with same delegate but different label or
        signer will update the label or delegator if a different one is provided
        For the signature we are using TOTP with `T0=0` and `Tx=3600`. TOTP is calculated by taking the
        Unix UTC epoch time (no milliseconds) and dividing by 3600 (natural division, no decimals)
        To generate the signature, this hash needs to be signed: keccak(checksummed address + str(int(current_epoch //
        3600)))
        As an example, if the 0x132512f995866CcE1b0092384A6118EDaF4508Ff delegate is added and epoch=1586779140:
             - `TOTP = epoch // 3600 = 1586779140 // 3600 = 440771`
             - keccak("0x132512f995866CcE1b0092384A6118EDaF4508Ff440771") would be the hash a Safe owner would
             need to sign.`
        """
        return super().post(request, **kwargs)


class DelegateDeleteView(GenericAPIView):
    """

    .. deprecated:: 4.38.0
       Deprecated in favor of V2 view supporting EIP712 signatures
    """

    serializer_class = serializers.DelegateDeleteSerializer

    @extend_schema(
        deprecated=True,
        request=serializer_class(),
        responses={
            204: OpenApiResponse(description="Deleted"),
            400: OpenApiResponse(description="Malformed data"),
            404: OpenApiResponse(description="Delegate not found"),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Invalid Ethereum address/Error processing data",
            ),
        },
    )
    def delete(self, request, delegate_address, *args, **kwargs):
        """
        Delete every pair delegate/delegator found. Signature is built the same way as for adding a delegate,
        but in this case the signer can be either the `delegator` (owner) or the `delegate` itself.
        Check `POST /delegates/`
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

        request.data["delegate"] = delegate_address
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deleted, _ = SafeContractDelegate.objects.filter(
            delegate=serializer.validated_data["delegate"],
            delegator=serializer.validated_data["delegator"],
        ).delete()
        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(status=status.HTTP_404_NOT_FOUND)


class SafeDelegateDestroyView(DestroyAPIView):
    """

    .. deprecated:: 4.38.0
       Deprecated in favor of V2 view supporting EIP712 signatures
    """

    serializer_class = serializers.SafeDelegateDeleteSerializer

    def get_object(self):
        return get_object_or_404(
            SafeContractDelegate,
            safe_contract_id=self.kwargs["address"],
            delegate=self.kwargs["delegate_address"],
        )

    @extend_schema(
        tags=["delegates"],
        deprecated=True,
        request=serializer_class(),
        responses={
            204: OpenApiResponse(description="Deleted"),
            400: OpenApiResponse(description="Malformed data"),
            404: OpenApiResponse(description="Delegate not found"),
            422: OpenApiResponse(
                response=serializers.CodeErrorResponse,
                description="Invalid Ethereum address | Error processing data",
            ),
        },
    )
    def delete(self, request, address, delegate_address, *args, **kwargs):
        """
        Delete a delegate for a Safe. Signature is built the same way that for adding a delegate.
        Check `POST /delegates/`
        """
        if not fast_is_checksum_address(address) or not fast_is_checksum_address(
            delegate_address
        ):
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 1,
                    "message": "Checksum address validation failed",
                    "arguments": [address, delegate_address],
                },
            )

        body_delegate = request.data.get("delegate", delegate_address)
        if (
            body_delegate != delegate_address
        ):  # Check delegate in body matches the one in url
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                data={
                    "code": 2,
                    "message": "Delegate address in body should match the one in the url",
                    "arguments": [body_delegate, delegate_address],
                },
            )

        request.data["safe"] = address
        request.data["delegate"] = delegate_address
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return super().delete(request, address, delegate_address, *args, **kwargs)
