import hashlib
from typing import Tuple

from django.conf import settings
from django.db.models import Count
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.filters import OrderingFilter
from rest_framework.generics import (CreateAPIView, DestroyAPIView,
                                     GenericAPIView, ListAPIView,
                                     ListCreateAPIView, RetrieveAPIView,
                                     get_object_or_404)
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from web3 import Web3

from gnosis.safe import CannotEstimateGas

from safe_transaction_service.tokens.models import Token
from safe_transaction_service.version import __version__

from . import filters, pagination, serializers
from .models import (InternalTx, ModuleTransaction, MultisigConfirmation,
                     MultisigTransaction, SafeContract, SafeContractDelegate,
                     SafeMasterCopy, SafeStatus, TransferDict)
from .serializers import get_data_decoded_from_data
from .services import (BalanceServiceProvider, SafeServiceProvider,
                       TransactionServiceProvider)
from .services.collectibles_service import CollectiblesServiceProvider
from .services.safe_service import CannotGetSafeInfo
from .utils import parse_boolean_query_param


class AboutView(APIView):
    """
    Returns information and configuration of the service
    """
    renderer_classes = (JSONRenderer,)

    @method_decorator(cache_page(60 * 60))  # Cache 1 hour
    def get(self, request, format=None):
        content = {
            'name': 'Safe Transaction Service',
            'version': __version__,
            'api_version': self.request.version,
            'secure': self.request.is_secure(),
            'settings': {
                'AWS_CONFIGURED': settings.AWS_CONFIGURED,
                'AWS_S3_CUSTOM_DOMAIN': settings.AWS_S3_CUSTOM_DOMAIN,
                'ETHEREUM_NODE_URL': settings.ETHEREUM_NODE_URL,
                'ETHEREUM_TRACING_NODE_URL': settings.ETHEREUM_TRACING_NODE_URL,
                'ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT': settings.ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT,
                'ETH_INTERNAL_NO_FILTER': settings.ETH_INTERNAL_NO_FILTER,
                'ETH_REORG_BLOCKS': settings.ETH_REORG_BLOCKS,
                'TOKENS_LOGO_BASE_URI': settings.TOKENS_LOGO_BASE_URI,
                'TOKENS_LOGO_EXTENSION': settings.TOKENS_LOGO_EXTENSION,
            }
        }
        return Response(content)


class AnalyticsMultisigTxsByOriginListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.AnalyticsMultisigTxsByOriginFilter
    pagination_class = None
    queryset = MultisigTransaction.objects.values('origin').annotate(transactions=Count('*')).order_by('-transactions')
    serializer_class = serializers.AnalyticsMultisigTxsByOriginResponseSerializer


class AnalyticsMultisigTxsBySafeListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.AnalyticsMultisigTxsBySafeFilter
    queryset = MultisigTransaction.objects.safes_with_number_of_transactions_executed_and_master_copy()
    serializer_class = serializers.AnalyticsMultisigTxsBySafeResponseSerializer


class AllTransactionsListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, OrderingFilter)
    pagination_class = pagination.SmallPagination
    serializer_class = serializers._AllTransactionsSchemaSerializer  # Just for docs, not used

    _schema_queued_param = openapi.Parameter('executed', openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN, default=False,
                                             description='If `True` only executed transactions are returned')
    _schema_queued_param = openapi.Parameter('queued', openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN, default=True,
                                             description='If `True` transactions with `nonce >= Safe current nonce` '
                                                         'are also returned')
    _schema_trusted_param = openapi.Parameter('trusted', openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN, default=True,
                                              description='If `True` just trusted transactions are shown (indexed, '
                                                          'added by a delegate or with at least one confirmation)')
    _schema_200_response = openapi.Response('A list with every element with the structure of one of these transaction'
                                            'types', serializers._AllTransactionsSchemaSerializer)

    def get_parameters(self) -> Tuple[bool, bool, bool]:
        """
        Parse query parameters:
        - queued: Default, True. If `queued=True` transactions with `nonce >= Safe current nonce` are also shown
        - trusted: Default, True. If `trusted=True` just trusted transactions are shown (indexed, added by a delegate
        or with at least one confirmation)
        :return: Tuple with queued, trusted
        """
        executed = parse_boolean_query_param(self.request.query_params.get('executed', False))
        queued = parse_boolean_query_param(self.request.query_params.get('queued', True))
        trusted = parse_boolean_query_param(self.request.query_params.get('trusted', True))
        return executed, queued, trusted

    def list(self, request, *args, **kwargs):
        transaction_service = TransactionServiceProvider()
        safe = self.kwargs['address']
        executed, queued, trusted = self.get_parameters()
        queryset = self.filter_queryset(transaction_service.get_all_tx_hashes(safe, executed=executed,
                                                                              queued=queued, trusted=trusted))
        page = self.paginate_queryset(queryset)

        if not page:
            return self.get_paginated_response([])

        all_tx_hashes = [element['safe_tx_hash'] for element in page]
        all_txs = transaction_service.get_all_txs_from_hashes(safe, all_tx_hashes)
        all_txs_serialized = transaction_service.serialize_all_txs(all_txs)
        return self.get_paginated_response(all_txs_serialized)

    @swagger_auto_schema(responses={200: _schema_200_response,
                                    422: 'code = 1: Checksum address validation failed'},
                         manual_parameters=[_schema_queued_param, _schema_trusted_param])
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
        """
        address = kwargs['address']
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data={'code': 1,
                                                                               'message': 'Checksum address validation failed',
                                                                               'arguments': [address]})

        response = super().get(request, *args, **kwargs)
        response.setdefault('ETag', 'W/' + hashlib.md5(str(response.data['results']).encode()).hexdigest())
        return response


class SafeModuleTransactionListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, OrderingFilter)
    filterset_class = filters.ModuleTransactionFilter
    ordering_fields = ['created']
    pagination_class = pagination.DefaultPagination
    serializer_class = serializers.SafeModuleTransactionResponseSerializer

    def get_queryset(self):
        return ModuleTransaction.objects.filter(
            safe=self.kwargs['address']
        ).select_related(
            'internal_tx__ethereum_tx__block'
        ).order_by(
            '-created'
        )

    @swagger_auto_schema(responses={400: 'Invalid data',
                                    422: 'Invalid ethereum address'})
    def get(self, request, address, format=None):
        """
        Returns the module transaction of a Safe
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        response = super().get(request, address)
        response.setdefault('ETag', 'W/' + hashlib.md5(str(response.data['results']).encode()).hexdigest())
        return response


class SafeMultisigConfirmationsView(ListCreateAPIView):
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        return MultisigConfirmation.objects.filter(multisig_transaction_id=self.kwargs['safe_tx_hash'])

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['safe_tx_hash'] = self.kwargs.get('safe_tx_hash')
        return context

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return serializers.SafeMultisigConfirmationResponseSerializer
        elif self.request.method == 'POST':
            return serializers.SafeMultisigConfirmationSerializer

    @swagger_auto_schema(responses={400: 'Invalid data'})
    def get(self, request, *args, **kwargs):
        """
        Get the list of confirmations for a multisig transaction
        """
        return super().get(request, *args, **kwargs)

    @swagger_auto_schema(responses={201: 'Created',
                                    400: 'Malformed data',
                                    422: 'Error processing data'})
    def post(self, request, *args, **kwargs):
        """
        Add a confirmation for a transaction. More than one signature can be used. This endpoint does not support
        the use of delegates to make a transaction trusted.
        """
        return super().post(request, *args, **kwargs)


@swagger_auto_schema(responses={200: 'Ok',
                                404: 'Not found'})
class SafeMultisigTransactionDetailView(RetrieveAPIView):
    serializer_class = serializers.SafeMultisigTransactionResponseSerializer
    lookup_field = 'safe_tx_hash'
    lookup_url_kwarg = 'safe_tx_hash'

    def get_queryset(self):
        return MultisigTransaction.objects.with_confirmations_required(
        ).prefetch_related(
            'confirmations'
        ).select_related(
            'ethereum_tx__block'
        )


class SafeMultisigTransactionListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, OrderingFilter)
    filterset_class = filters.MultisigTransactionFilter
    ordering_fields = ['nonce', 'created']
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        return MultisigTransaction.objects.filter(
            safe=self.kwargs['address']
        ).with_confirmations_required(
        ).prefetch_related(
            'confirmations'
        ).select_related(
            'ethereum_tx__block'
        ).order_by(
            '-nonce',
            '-created'
        )

    def get_unique_nonce(self, address: str):
        return MultisigTransaction.objects.filter(safe=address).distinct('nonce').count()

    def get_serializer_class(self):
        """
        Proxy returning a serializer class according to the request's verb.
        """
        if self.request.method == 'GET':
            return serializers.SafeMultisigTransactionResponseSerializer
        elif self.request.method == 'POST':
            return serializers.SafeMultisigTransactionSerializer

    @swagger_auto_schema(responses={400: 'Invalid data',
                                    422: 'Invalid ethereum address'})
    def get(self, request, *args, **kwargs):
        """
        Returns the history of a multisig tx (safe)
        """
        address = kwargs['address']
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        response = super().get(request, *args, **kwargs)
        response.data['count_unique_nonce'] = self.get_unique_nonce(address) if response.data['count'] else 0
        response.setdefault('ETag', 'W/' + hashlib.md5(str(response.data['results']).encode()).hexdigest())
        return response

    @swagger_auto_schema(responses={201: 'Created or signature updated',
                                    400: 'Invalid data',
                                    422: 'Invalid ethereum address/User is not an owner/Invalid safeTxHash/'
                                         'Invalid signature/Nonce already executed/Sender is not an owner'})
    def post(self, request, address, format=None):
        """
        Creates a Multisig Transaction with its confirmations and retrieves all the information related.
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        request.data['safe'] = address
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors)
        else:
            serializer.save()
            return Response(status=status.HTTP_201_CREATED)


def swagger_safe_balance_schema(serializer_class):
    _schema_token_trusted_param = openapi.Parameter('trusted', openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
                                                    default=False,
                                                    description='If `True` just trusted tokens will be returned')
    _schema_token_exclude_spam_param = openapi.Parameter('exclude_spam', openapi.IN_QUERY, type=openapi.TYPE_BOOLEAN,
                                                         default=False,
                                                         description='If `True` spam tokens will not be returned')
    return swagger_auto_schema(responses={200: serializer_class(many=True),
                                          404: 'Safe not found',
                                          422: 'Safe address checksum not valid'},
                               manual_parameters=[_schema_token_trusted_param,
                                                  _schema_token_exclude_spam_param])


class SafeBalanceView(APIView):
    serializer_class = serializers.SafeBalanceResponseSerializer

    def get_parameters(self) -> Tuple[bool, bool]:
        """
        Parse query parameters:
        :return: Tuple with only_trusted, exclude_spam
        """
        only_trusted = parse_boolean_query_param(self.request.query_params.get('trusted', False))
        exclude_spam = parse_boolean_query_param(self.request.query_params.get('exclude_spam', False))
        return only_trusted, exclude_spam

    def get_result(self, *args, **kwargs):
        return BalanceServiceProvider().get_balances(*args, **kwargs)

    @swagger_safe_balance_schema(serializer_class)
    @method_decorator(cache_page(20))
    def get(self, request, address):
        """
        Get balance for Ether and ERC20 tokens
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            data={'code': 1,
                                  'message': 'Checksum address validation failed',
                                  'arguments': [address]})
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            only_trusted, exclude_spam = self.get_parameters()
            safe_balances = self.get_result(address, only_trusted=only_trusted, exclude_spam=exclude_spam)
            serializer = self.serializer_class(safe_balances, many=True)
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeBalanceUsdView(SafeBalanceView):
    serializer_class = serializers.SafeBalanceUsdResponseSerializer

    def get_result(self, *args, **kwargs):
        return BalanceServiceProvider().get_usd_balances(*args, **kwargs)

    @swagger_safe_balance_schema(serializer_class)
    @method_decorator(cache_page(20))
    def get(self, *args, **kwargs):
        """
        Get balance for Ether and ERC20 tokens with USD fiat conversion
        """
        return super().get(*args, **kwargs)


class SafeCollectiblesView(SafeBalanceView):
    serializer_class = serializers.SafeCollectibleResponseSerializer

    def get_result(self, *args, **kwargs):
        return CollectiblesServiceProvider().get_collectibles_with_metadata(*args, **kwargs)

    @swagger_safe_balance_schema(serializer_class)
    @method_decorator(cache_page(15))
    def get(self, *args, **kwargs):
        """
        Get collectibles (ERC721 tokens) and information about them
        """
        return super().get(*args, **kwargs)


class SafeDelegateListView(ListCreateAPIView):
    pagination_class = pagination.DefaultPagination

    def get_queryset(self):
        return SafeContractDelegate.objects.filter(
            safe_contract_id=self.kwargs['address']
        )

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return serializers.SafeDelegateResponseSerializer
        elif self.request.method == 'POST':
            return serializers.SafeDelegateSerializer

    @swagger_auto_schema(responses={400: 'Invalid data',
                                    422: 'Invalid Ethereum address'})
    def get(self, request, address, **kwargs):
        """
        Get the list of delegates for a Safe address
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        return super().get(request, address, **kwargs)

    @swagger_auto_schema(responses={202: 'Accepted',
                                    400: 'Malformed data',
                                    422: 'Invalid Ethereum address/Error processing data'})
    def post(self, request, address, **kwargs):
        """
        Create a delegate for a Safe address with a custom label. Calls with same delegate but different label or
        signer will update the label or delegator if different.
        For the signature we are using TOTP with `T0=0` and `Tx=3600`. TOTP is calculated by taking the
        Unix UTC epoch time (no milliseconds) and dividing by 3600 (natural division, no decimals)
        For signature this hash need to be signed: keccak(address + str(int(current_epoch // 3600)))
        For example:
             - we want to add the owner `0x132512f995866CcE1b0092384A6118EDaF4508Ff` and `epoch=1586779140`.
             - TOTP = epoch // 3600 = 1586779140 // 3600 = 440771
             - The hash to sign by a Safe owner would be `keccak("0x132512f995866CcE1b0092384A6118EDaF4508Ff440771")`
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        request.data['safe'] = address
        return super().post(request, address, **kwargs)


class SafeDelegateDestroyView(DestroyAPIView):
    serializer_class = serializers.SafeDelegateDeleteSerializer

    def get_object(self):
        return get_object_or_404(SafeContractDelegate,
                                 safe_contract_id=self.kwargs['address'],
                                 delegate=self.kwargs['delegate_address'])

    @swagger_auto_schema(
        request_body=serializer_class(),
        responses={204: 'Deleted',
                   400: 'Malformed data',
                   404: 'Delegate not found',
                   422: 'Invalid Ethereum address/Error processing data'})
    def delete(self, request, address, delegate_address, *args, **kwargs):
        """
        Delete a delegate for a Safe. Signature is built the same way that for adding a delegate.
        Check `POST /delegates/`
        """
        if not Web3.isChecksumAddress(address) or not Web3.isChecksumAddress(delegate_address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        request.data['safe'] = address
        request.data['delegate'] = delegate_address
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return super().delete(request, address, delegate_address, *args, **kwargs)


class SafeTransferListView(ListAPIView):
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    filterset_class = filters.TransferListFilter
    serializer_class = serializers.TransferWithTokenInfoResponseSerializer
    pagination_class = pagination.DefaultPagination

    def list(self, request, *args, **kwargs):
        # Queryset must be already filtered, as we cannot filter a union
        # queryset = self.filter_queryset(self.get_queryset())

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def add_tokens_to_transfers(self, transfers: TransferDict) -> TransferDict:
        tokens = {token.address: token
                  for token in Token.objects.filter(address__in={transfer['token_address'] for transfer in transfers
                                                                 if transfer['token_address']})}
        for transfer in transfers:
            transfer['token'] = tokens.get(transfer['token_address'])
        return transfers

    def get_transfers(self, address: str):
        tokens_queryset = super().filter_queryset(InternalTx.objects.token_txs_for_address(address))
        ether_queryset = super().filter_queryset(InternalTx.objects.ether_txs_for_address(address))
        return InternalTx.objects.union_ether_and_token_txs(tokens_queryset, ether_queryset)

    def get_queryset(self):
        address = self.kwargs['address']
        return self.add_tokens_to_transfers(self.get_transfers(address))

    @swagger_auto_schema(responses={200: serializers.TransferResponseSerializer(many=True),
                                    422: 'Safe address checksum not valid'})
    def get(self, request, address, format=None):
        """
        Returns the history of a multisig tx (safe)
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        response = super().get(request, address)
        response.setdefault('ETag', 'W/' + hashlib.md5(str(response.data['results']).encode()).hexdigest())
        return response


class SafeIncomingTransferListView(SafeTransferListView):
    def get_transfers(self, address: str):
        tokens_queryset = super().filter_queryset(InternalTx.objects.token_incoming_txs_for_address(address))
        ether_queryset = super().filter_queryset(InternalTx.objects.ether_incoming_txs_for_address(address))
        return InternalTx.objects.union_ether_and_token_txs(tokens_queryset, ether_queryset)


class SafeCreationView(APIView):
    serializer_class = serializers.SafeCreationInfoResponseSerializer

    @swagger_auto_schema(responses={200: serializer_class(),
                                    404: 'Safe creation not found',
                                    422: 'Owner address checksum not valid',
                                    503: 'Problem connecting to Ethereum network'})
    @method_decorator(cache_page(60 * 60))  # 1 hour
    def get(self, request, address, *args, **kwargs):
        """
        Get status of the safe
        """

        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        safe_creation_info = SafeServiceProvider().get_safe_creation_info(address)
        if not safe_creation_info:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = self.serializer_class(safe_creation_info)
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeInfoView(APIView):
    serializer_class = serializers.SafeInfoResponseSerializer

    @swagger_auto_schema(responses={200: serializer_class(),
                                    404: 'Safe not found',
                                    422: 'code = 1: Checksum address validation failed\ncode = 50: Cannot get Safe info'})
    def get(self, request, address, *args, **kwargs):
        """
        Get status of the safe
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data={'code': 1,
                                                                               'message': 'Checksum address validation failed',
                                                                               'arguments': [address]})

        if not SafeContract.objects.filter(address=address).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            safe_info = SafeServiceProvider().get_safe_info(address)
            serializer = self.serializer_class(safe_info)
            return Response(status=status.HTTP_200_OK, data=serializer.data)
        except CannotGetSafeInfo:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data={'code': 50,
                                                                               'message': 'Cannot get Safe info',
                                                                               'arguments': [address]})


class MasterCopiesView(ListAPIView):
    serializer_class = serializers.MasterCopyResponseSerializer
    queryset = SafeMasterCopy.objects.all()
    pagination_class = None


class OwnersView(APIView):
    serializer_class = serializers.OwnerResponseSerializer

    @swagger_auto_schema(responses={200: serializers.OwnerResponseSerializer(),
                                    422: 'Owner address checksum not valid'})
    def get(self, request, address, *args, **kwargs):
        """
        Return Safes where the address provided is an owner
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        safes_for_owner = SafeStatus.objects.addresses_for_owner(address)
        serializer = self.serializer_class(data={'safes': safes_for_owner})
        assert serializer.is_valid()
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class DataDecoderView(GenericAPIView):
    def get_serializer_class(self):
        return serializers.DataDecoderSerializer

    @swagger_auto_schema(responses={200: 'Decoded data',
                                    404: 'Cannot find function selector to decode data',
                                    422: 'Invalid data'})
    def post(self, request, format=None):
        """
        Creates a Multisig Transaction with its confirmations and retrieves all the information related.
        """

        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors)
        else:
            data_decoded = get_data_decoded_from_data(serializer.data['data'])
            if data_decoded:
                return Response(status=status.HTTP_200_OK, data=data_decoded)
            else:
                return Response(status=status.HTTP_404_NOT_FOUND, data=data_decoded)


class SafeMultisigTransactionEstimateView(CreateAPIView):
    serializer_class = serializers.SafeMultisigTransactionEstimateSerializer
    response_serializer = serializers.SafeMultisigTransactionEstimateResponseSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['safe_address'] = self.kwargs['address']
        return context

    @swagger_auto_schema(responses={200: response_serializer,
                                    400: 'Data not valid',
                                    404: 'Safe not found',
                                    422: 'Tx not valid'})
    def post(self, request, address, *args, **kwargs):
        """
        Estimates a Safe Multisig Transaction. `operational_gas` and `data_gas` are deprecated, use `base_gas` instead
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if not SafeContract.objects.filter(address=address).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            try:
                response_serializer = self.response_serializer(data=serializer.save())
                response_serializer.is_valid(raise_exception=True)
                return Response(status=status.HTTP_200_OK, data=response_serializer.data)
            except CannotEstimateGas:
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
