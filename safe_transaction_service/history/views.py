import hashlib
import logging
from typing import Any, Dict, Tuple

from django.conf import settings
from django.db.models import Count
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
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

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import fast_is_checksum_address
from gnosis.safe import CannotEstimateGas

from safe_transaction_service import __version__
from safe_transaction_service.tokens.models import Token
from safe_transaction_service.utils.utils import parse_boolean_query_param

from . import filters, pagination, serializers
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
from .serializers import get_data_decoded_from_data
from .services import (
    BalanceServiceProvider,
    SafeServiceProvider,
    TransactionServiceProvider,
)
from .services.collectibles_service import CollectiblesServiceProvider
from .services.safe_service import CannotGetSafeInfoFromBlockchain

logger = logging.getLogger(__name__)


class AboutView(APIView):
    """
    Returns information and configuration of the service
    """

    renderer_classes = (JSONRenderer,)

    @method_decorator(cache_page(60 * 60))  # 1 hour
    def get(self, request, format=None):
        content = {
            "name": "Safe Transaction Service",
            "version": __version__,
            "api_version": request.version,
            "secure": request.is_secure(),
            "host": request.get_host(),
            "headers": [x for x in request.META.keys() if "FORWARD" in x],
            "settings": {
                "AWS_CONFIGURED": settings.AWS_CONFIGURED,
                "AWS_S3_BUCKET_NAME": settings.AWS_S3_BUCKET_NAME,
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
                "NOTIFICATIONS_FIREBASE_CREDENTIALS_PATH": settings.NOTIFICATIONS_FIREBASE_CREDENTIALS_PATH,
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
            client_version = ethereum_client.w3.clientVersion
        except (IOError, ValueError):
            client_version = "Error getting client version"

        try:
            syncing = ethereum_client.w3.eth.syncing
        except (IOError, ValueError):
            syncing = "Error getting syncing status"

        ethereum_network = ethereum_client.get_network()
        return {
            "version": client_version,
            "block_number": ethereum_client.current_block_number,
            "chain_id": ethereum_network.value,
            "chain": ethereum_network.name,
            "syncing": syncing,
        }

    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, format=None):
        """
        Get information about the Ethereum RPC node used by the service
        """
        ethereum_client = EthereumClientProvider()
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


class AnalyticsMultisigTxsByOriginListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.AnalyticsMultisigTxsByOriginFilter
    pagination_class = None
    queryset = (
        MultisigTransaction.objects.values("origin")
        .annotate(transactions=Count("*"))
        .order_by("-transactions")
    )
    serializer_class = serializers.AnalyticsMultisigTxsByOriginResponseSerializer


class AnalyticsMultisigTxsBySafeListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.AnalyticsMultisigTxsBySafeFilter
    queryset = (
        MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
    )
    serializer_class = serializers.AnalyticsMultisigTxsBySafeResponseSerializer


class AllTransactionsListView(ListAPIView):
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    )
    ordering_fields = ["execution_date", "safe_nonce", "block", "created"]
    pagination_class = pagination.SmallPagination
    serializer_class = (
        serializers.AllTransactionsSchemaSerializer
    )  # Just for docs, not used

    _schema_executed_param = openapi.Parameter(
        "executed",
        openapi.IN_QUERY,
        type=openapi.TYPE_BOOLEAN,
        default=False,
        description="If `True` only executed transactions are returned",
    )
    _schema_queued_param = openapi.Parameter(
        "queued",
        openapi.IN_QUERY,
        type=openapi.TYPE_BOOLEAN,
        default=True,
        description="If `True` transactions with `nonce >= Safe current nonce` "
        "are also returned",
    )
    _schema_trusted_param = openapi.Parameter(
        "trusted",
        openapi.IN_QUERY,
        type=openapi.TYPE_BOOLEAN,
        default=True,
        description="If `True` just trusted transactions are shown (indexed, "
        "added by a delegate or with at least one confirmation)",
    )
    _schema_200_response = openapi.Response(
        "A list with every element with the structure of one of these transaction"
        "types",
        serializers.AllTransactionsSchemaSerializer,
    )

    def get_parameters(self) -> Tuple[bool, bool, bool]:
        """
        Parse query parameters:
        - queued: Default, True. If `queued=True` transactions with `nonce >= Safe current nonce` are also shown
        - trusted: Default, True. If `trusted=True` just trusted transactions are shown (indexed, added by a delegate
        or with at least one confirmation)
        :return: Tuple with queued, trusted
        """
        executed = parse_boolean_query_param(
            self.request.query_params.get("executed", False)
        )
        queued = parse_boolean_query_param(
            self.request.query_params.get("queued", True)
        )
        trusted = parse_boolean_query_param(
            self.request.query_params.get("trusted", True)
        )
        return executed, queued, trusted

    def list(self, request, *args, **kwargs):
        transaction_service = TransactionServiceProvider()
        safe = self.kwargs["address"]
        executed, queued, trusted = self.get_parameters()
        queryset = self.filter_queryset(
            transaction_service.get_all_tx_hashes(
                safe, executed=executed, queued=queued, trusted=trusted
            )
        )
        page = self.paginate_queryset(queryset)

        if not page:
            return self.get_paginated_response([])

        all_tx_hashes = [element["safe_tx_hash"] for element in page]
        all_txs = transaction_service.get_all_txs_from_hashes(safe, all_tx_hashes)
        all_txs_serialized = transaction_service.serialize_all_txs(all_txs)
        return self.get_paginated_response(all_txs_serialized)

    @swagger_auto_schema(
        responses={
            200: _schema_200_response,
            422: "code = 1: Checksum address validation failed",
        },
        manual_parameters=[
            _schema_executed_param,
            _schema_queued_param,
            _schema_trusted_param,
        ],
    )
    def get(self, request, *args, **kwargs):
        """
        Returns a paginated list of transactions for a Safe. The list has different structures depending on the
        transaction type:
        - Multisig Transactions for a Safe. `tx_type=MULTISIG_TRANSACTION`. If the query parameter `queued=False` is
        set only the transactions with `safe nonce < current Safe nonce` will be displayed. By default, only the
        `trusted` transactions will be displayed (transactions indexed, with at least one confirmation or proposed
        by a delegate). If you need that behaviour to be disabled set the query parameter `trusted=False`
        - Module Transactions for a Safe. `tx_type=MODULE_TRANSACTION`
        - Incoming Transfers of Ether/ERC20 Tokens/ERC721 Tokens. `tx_type=ETHEREUM_TRANSACTION`
        Ordering_fields: ["execution_date", "safe_nonce", "block", "created"] eg: `created` or `-created`
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
        response.setdefault(
            "ETag",
            "W/" + hashlib.md5(str(response.data["results"]).encode()).hexdigest(),
        )
        return response


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
        return (
            ModuleTransaction.objects.filter(safe=self.kwargs["address"])
            .select_related("internal_tx__ethereum_tx__block")
            .order_by("-created")
        )

    @swagger_auto_schema(
        responses={400: "Invalid data", 422: "Invalid ethereum address"}
    )
    def get(self, request, address, format=None):
        """
        Returns the module transaction of a Safe
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

    @swagger_auto_schema(responses={400: "Invalid data"})
    def get(self, request, *args, **kwargs):
        """
        Get the list of confirmations for a multisig transaction
        """
        return super().get(request, *args, **kwargs)

    @swagger_auto_schema(
        responses={201: "Created", 400: "Malformed data", 422: "Error processing data"}
    )
    def post(self, request, *args, **kwargs):
        """
        Add a confirmation for a transaction. More than one signature can be used. This endpoint does not support
        the use of delegates to make a transaction trusted.
        """
        return super().post(request, *args, **kwargs)


class SafeMultisigTransactionDetailView(RetrieveAPIView):
    serializer_class = serializers.SafeMultisigTransactionResponseSerializer
    lookup_field = "safe_tx_hash"
    lookup_url_kwarg = "safe_tx_hash"

    def get_queryset(self):
        return (
            MultisigTransaction.objects.with_confirmations_required()
            .prefetch_related("confirmations")
            .select_related("ethereum_tx__block")
        )


class SafeMultisigTransactionDeprecatedDetailView(SafeMultisigTransactionDetailView):
    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use `multisig-transactions` instead of `transactions`",
        responses={200: "Ok", 404: "Not found"},
    )
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)


class SafeMultisigTransactionListView(ListAPIView):
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend,
        OrderingFilter,
    )
    filterset_class = filters.MultisigTransactionFilter
    ordering_fields = ["nonce", "created", "modified"]
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        return (
            MultisigTransaction.objects.filter(safe=self.kwargs["address"])
            .with_confirmations_required()
            .prefetch_related("confirmations")
            .select_related("ethereum_tx__block")
            .order_by("-nonce", "-created")
        )

    def get_unique_nonce(self, address: str):
        return (
            MultisigTransaction.objects.filter(safe=address).distinct("nonce").count()
        )

    def get_serializer_class(self):
        """
        Proxy returning a serializer class according to the request's verb.
        """
        if self.request.method == "GET":
            return serializers.SafeMultisigTransactionResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeMultisigTransactionSerializer

    @swagger_auto_schema(
        responses={400: "Invalid data", 422: "Invalid ethereum address"}
    )
    def get(self, request, *args, **kwargs):
        """
        Returns the history of a multisig tx (safe)
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
        response.data["count_unique_nonce"] = (
            self.get_unique_nonce(address) if response.data["count"] else 0
        )
        return response

    @swagger_auto_schema(
        responses={
            201: "Created or signature updated",
            400: "Invalid data",
            422: "Invalid ethereum address/User is not an owner/Invalid safeTxHash/"
            "Invalid signature/Nonce already executed/Sender is not an owner",
        }
    )
    def post(self, request, address, format=None):
        """
        Creates a Multisig Transaction with its confirmations and retrieves all the information related.
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

        if not serializer.is_valid():
            return Response(
                status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors
            )
        else:
            serializer.save()
            return Response(status=status.HTTP_201_CREATED)


class SafeMultisigTransactionDeprecatedListView(SafeMultisigTransactionListView):
    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use `multisig-transactions` instead of `transactions`",
    )
    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use `multisig-transactions` instead of `transactions`",
    )
    def post(self, *args, **kwargs):
        return super().post(*args, **kwargs)


def swagger_safe_balance_schema(serializer_class):
    _schema_token_trusted_param = openapi.Parameter(
        "trusted",
        openapi.IN_QUERY,
        type=openapi.TYPE_BOOLEAN,
        default=False,
        description="If `True` just trusted tokens will be returned",
    )
    _schema_token_exclude_spam_param = openapi.Parameter(
        "exclude_spam",
        openapi.IN_QUERY,
        type=openapi.TYPE_BOOLEAN,
        default=False,
        description="If `True` spam tokens will not be returned",
    )
    return swagger_auto_schema(
        responses={
            200: serializer_class(many=True),
            404: "Safe not found",
            422: "Safe address checksum not valid",
        },
        manual_parameters=[
            _schema_token_trusted_param,
            _schema_token_exclude_spam_param,
        ],
    )


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

    def get_result(self, *args, **kwargs):
        return BalanceServiceProvider().get_balances(*args, **kwargs)

    @swagger_safe_balance_schema(serializer_class)
    def get(self, request, address):
        """
        Get balance for Ether and ERC20 tokens
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
            safe_balances = self.get_result(
                address, only_trusted=only_trusted, exclude_spam=exclude_spam
            )
            serializer = self.get_serializer(safe_balances, many=True)
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeBalanceUsdView(SafeBalanceView):
    serializer_class = serializers.SafeBalanceUsdResponseSerializer

    def get_result(self, *args, **kwargs):
        return BalanceServiceProvider().get_usd_balances(*args, **kwargs)

    @swagger_safe_balance_schema(serializer_class)
    def get(self, *args, **kwargs):
        """
        Get balance for Ether and ERC20 tokens with USD fiat conversion
        """
        return super().get(*args, **kwargs)


class SafeCollectiblesView(SafeBalanceView):
    serializer_class = serializers.SafeCollectibleResponseSerializer

    def get_result(self, *args, **kwargs):
        return CollectiblesServiceProvider().get_collectibles_with_metadata(
            *args, **kwargs
        )

    @swagger_safe_balance_schema(serializer_class)
    def get(self, *args, **kwargs):
        """
        Get collectibles (ERC721 tokens) and information about them
        """
        return super().get(*args, **kwargs)


class SafeDelegateListView(ListCreateAPIView):
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        return SafeContractDelegate.objects.filter(
            safe_contract_id=self.kwargs["address"]
        )

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeDelegateResponseSerializer
        elif self.request.method == "POST":
            return serializers.SafeDelegateSerializer
        elif self.request.method == "DELETE":
            return serializers.SafeDelegateDeleteSerializer

    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use /delegates endpoint",
        responses={400: "Invalid data", 422: "Invalid Ethereum address"},
    )
    def get(self, request, address, **kwargs):
        """
        Get the list of delegates for a Safe address
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

        return super().get(request, address, **kwargs)

    @swagger_auto_schema(
        deprecated=True,
        operation_description="Use /delegates endpoint",
        responses={
            202: "Accepted",
            400: "Malformed data",
            422: "Invalid Ethereum address/Error processing data",
        },
    )
    def post(self, request, address, **kwargs):
        """
        Create a delegate for a Safe address with a custom label. Calls with same delegate but different label or
        signer will update the label or delegator if different.
        For the signature we are using TOTP with `T0=0` and `Tx=3600`. TOTP is calculated by taking the
        Unix UTC epoch time (no milliseconds) and dividing by 3600 (natural division, no decimals)
        For signature this hash need to be signed: keccak(checksummed address + str(int(current_epoch // 3600)))
        For example:
             - We want to add the delegate `0x132512f995866CcE1b0092384A6118EDaF4508Ff` and `epoch=1586779140`.
             - `TOTP = epoch // 3600 = 1586779140 // 3600 = 440771`
             - The hash to sign by a Safe owner would be `keccak("0x132512f995866CcE1b0092384A6118EDaF4508Ff440771")`
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
        return super().post(request, address, **kwargs)

    @swagger_auto_schema(
        operation_id="safes_delegates_delete_all",
        deprecated=True,
        operation_description="Use /delegates endpoint",
        responses={
            204: "Deleted",
            400: "Malformed data",
            422: "Invalid Ethereum address/Error processing data",
        },
    )
    def delete(self, request, address, *args, **kwargs):
        """
        Delete all delegates for a Safe. Signature is built the same way that for adding a delegate using the Safe
        address as the delegate.

        Check `POST /delegates/`
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
        request.data["delegate"] = address
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        SafeContractDelegate.objects.filter(safe_contract_id=address).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SafeDelegateDestroyView(DestroyAPIView):
    serializer_class = serializers.SafeDelegateDeleteSerializer

    def get_object(self):
        return get_object_or_404(
            SafeContractDelegate,
            safe_contract_id=self.kwargs["address"],
            delegate=self.kwargs["delegate_address"],
        )

    @swagger_auto_schema(
        request_body=serializer_class(),
        responses={
            204: "Deleted",
            400: "Malformed data",
            404: "Delegate not found",
            422: "Invalid Ethereum address/Error processing data",
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

        request.data["safe"] = address
        request.data["delegate"] = delegate_address
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return super().delete(request, address, delegate_address, *args, **kwargs)


class DelegateListView(ListCreateAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.DelegateListFilter
    pagination_class = pagination.DefaultPagination
    queryset = SafeContractDelegate.objects.all()

    def get_serializer_class(self):
        if self.request.method == "GET":
            return serializers.SafeDelegateResponseSerializer
        elif self.request.method == "POST":
            return serializers.DelegateSerializer

    @swagger_auto_schema(responses={400: "Invalid data"})
    def get(self, request, **kwargs):
        """
        Get list of delegates
        """
        return super().get(request, **kwargs)

    @swagger_auto_schema(responses={202: "Accepted", 400: "Malformed data"})
    def post(self, request, **kwargs):
        """
        Create a delegate for a Safe address with a custom label. Calls with same delegate but different label or
        signer will update the label or delegator if different.
        For the signature we are using TOTP with `T0=0` and `Tx=3600`. TOTP is calculated by taking the
        Unix UTC epoch time (no milliseconds) and dividing by 3600 (natural division, no decimals)
        For signature this hash need to be signed: keccak(checksummed address + str(int(current_epoch // 3600)))
        For example:
             - We want to add the delegate `0x132512f995866CcE1b0092384A6118EDaF4508Ff` and `epoch=1586779140`.
             - `TOTP = epoch // 3600 = 1586779140 // 3600 = 440771`
             - The hash to sign by a Safe owner would be `keccak("0x132512f995866CcE1b0092384A6118EDaF4508Ff440771")`
        """
        return super().post(request, **kwargs)


class DelegateDeleteView(GenericAPIView):
    serializer_class = serializers.DelegateDeleteSerializer

    @swagger_auto_schema(
        request_body=serializer_class(),
        responses={
            204: "Deleted",
            400: "Malformed data",
            404: "Delegate not found",
            422: "Invalid Ethereum address/Error processing data",
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


class SafeTransferListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.TransferListFilter
    serializer_class = serializers.TransferWithTokenInfoResponseSerializer
    pagination_class = pagination.DefaultPagination

    def add_tokens_to_transfers(self, transfers: TransferDict) -> TransferDict:
        tokens = {
            token.address: token
            for token in Token.objects.filter(
                address__in={
                    transfer["token_address"]
                    for transfer in transfers
                    if transfer["token_address"]
                }
            )
        }
        for transfer in transfers:
            transfer["token"] = tokens.get(transfer["token_address"])
        return transfers

    def get_transfers(self, address: str):
        erc20_queryset = self.filter_queryset(
            ERC20Transfer.objects.to_or_from(address).token_txs()
        )
        erc721_queryset = self.filter_queryset(
            ERC721Transfer.objects.to_or_from(address).token_txs()
        )
        ether_queryset = self.filter_queryset(
            InternalTx.objects.ether_txs_for_address(address)
        )
        return InternalTx.objects.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )

    def get_queryset(self):
        address = self.kwargs["address"]
        return self.get_transfers(address)

    def list(self, request, *args, **kwargs):
        # Queryset must be already filtered, as we cannot filter a union
        # queryset = self.filter_queryset(self.get_queryset())

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(
                self.add_tokens_to_transfers(page), many=True
            )
            return self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(
                self.add_tokens_to_transfers(queryset), many=True
            )
            return Response(serializer.data)

    @swagger_auto_schema(
        responses={
            200: serializers.TransferWithTokenInfoResponseSerializer(many=True),
            422: "Safe address checksum not valid",
        }
    )
    def get(self, request, address, format=None):
        """
        Returns ether/tokens transfers for a Safe
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
    @swagger_auto_schema(
        responses={
            200: serializers.TransferWithTokenInfoResponseSerializer(many=True),
            422: "Safe address checksum not valid",
        }
    )
    def get(self, *args, **kwargs):
        """
        Returns incoming ether/tokens transfers for a Safe
        """
        return super().get(*args, **kwargs)

    def get_transfers(self, address: str):
        erc20_queryset = self.filter_queryset(
            ERC20Transfer.objects.incoming(address).token_txs()
        )
        erc721_queryset = self.filter_queryset(
            ERC721Transfer.objects.incoming(address).token_txs()
        )
        ether_queryset = self.filter_queryset(
            InternalTx.objects.ether_incoming_txs_for_address(address)
        )
        return InternalTx.objects.union_ether_and_token_txs(
            erc20_queryset, erc721_queryset, ether_queryset
        )


class SafeCreationView(GenericAPIView):
    serializer_class = serializers.SafeCreationInfoResponseSerializer

    @swagger_auto_schema(
        responses={
            200: serializer_class(),
            404: "Safe creation not found",
            422: "Owner address checksum not valid",
            503: "Problem connecting to Ethereum network",
        }
    )
    @method_decorator(cache_page(60 * 60))  # 1 hour
    def get(self, request, address, *args, **kwargs):
        """
        Get status of the safe
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

    @swagger_auto_schema(
        responses={
            200: serializer_class(),
            404: "Safe not found",
            422: "code = 1: Checksum address validation failed\ncode = 50: Cannot get Safe info",
        }
    )
    def get(self, request, address, *args, **kwargs):
        """
        Get status of the safe
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


class MasterCopiesView(ListAPIView):
    serializer_class = serializers.MasterCopyResponseSerializer
    pagination_class = None

    def get_queryset(self):
        return SafeMasterCopy.objects.relevant()


class ModulesView(GenericAPIView):
    serializer_class = serializers.ModulesResponseSerializer

    @swagger_auto_schema(
        responses={
            200: serializers.ModulesResponseSerializer(),
            422: "Module address checksum not valid",
        }
    )
    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, address, *args, **kwargs):
        """
        Return Safes where the module address provided is enabled
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

    @swagger_auto_schema(
        responses={
            200: serializers.OwnerResponseSerializer(),
            422: "Owner address checksum not valid",
        }
    )
    @method_decorator(cache_page(15))  # 15 seconds
    def get(self, request, address, *args, **kwargs):
        """
        Return Safes where the address provided is an owner
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

    @swagger_auto_schema(
        responses={
            200: "Decoded data",
            404: "Cannot find function selector to decode data",
            422: "Invalid data",
        }
    )
    def post(self, request, format=None):
        """
        Returns decoded information using tx service internal ABI information given the tx
        data as a `0x` prefixed hexadecimal string.
        If address of the receiving contract is provided decoded data will be more accurate,
        as in case of ABI collision service will know which ABI to use.
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

    @swagger_auto_schema(
        responses={
            200: response_serializer,
            400: "Data not valid",
            404: "Safe not found",
            422: "Tx not valid",
        }
    )
    def post(self, request, address, *args, **kwargs):
        """
        Estimates `safeTxGas` for a Safe Multisig Transaction.
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
