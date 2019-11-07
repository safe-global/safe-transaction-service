from django.conf import settings

import django_filters
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from web3 import Web3

from safe_transaction_service.version import __version__

from .filters import DefaultPagination, MultisigTransactionFilter
from .models import (EthereumEvent, EthereumTxCallType, InternalTx,
                     MultisigTransaction, SafeContract)
from .serializers import (IncomingTransactionResponseSerializer,
                          SafeBalanceResponseSerializer,
                          SafeMultisigTransactionResponseSerializer,
                          SafeMultisigTransactionSerializer)
from .services import BalanceServiceProvider


class AboutView(APIView):
    """
    Returns info about the project.
    """
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        content = {
            'name': 'Safe Transaction Service',
            'version': __version__,
            'api_version': self.request.version,
            'secure': self.request.is_secure(),
            'settings': {
                'ETHEREUM_NODE_URL': settings.ETHEREUM_NODE_URL,
                'ETHEREUM_TRACING_NODE_URL': settings.ETHEREUM_TRACING_NODE_URL,
                'ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT ': settings.ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT,
                'ETH_REORG_BLOCKS': settings.ETH_REORG_BLOCKS,
            }
        }
        return Response(content)


@swagger_auto_schema(responses={200: 'Ok',
                                404: 'Not found'})
class SafeMultisigTransactionDetailView(RetrieveAPIView):
    serializer_class = SafeMultisigTransactionResponseSerializer
    lookup_field = 'safe_tx_hash'
    lookup_url_kwarg = 'tx_hash'

    def get_queryset(self):
        return MultisigTransaction.objects.prefetch_related(
            'confirmations'
        ).select_related(
            'ethereum_tx'
        )


class SafeMultisigTransactionListView(ListAPIView):
    pagination_class = DefaultPagination
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, )
    filterset_class = MultisigTransactionFilter

    def get_queryset(self):
        return MultisigTransaction.objects.filter(
            safe=self.kwargs['address']
        ).prefetch_related(
            'confirmations'
        ).select_related(
            'ethereum_tx'
        ).order_by(
            '-nonce'
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # TODO I think this is not useful anymore
        # Check if the 'owners' query parameter was passed in input
        query_owners = self.request.query_params.get('owners', None)
        if query_owners:
            context['owners'] = [owner for owner in query_owners.split(',') if owner != '']
        return context

    def get_serializer_class(self):
        """
        Proxy returning a serializer class according to the request's verb.
        """
        if self.request.method == 'GET':
            return SafeMultisigTransactionResponseSerializer
        elif self.request.method == 'POST':
            return SafeMultisigTransactionSerializer

    @swagger_auto_schema(responses={400: 'Invalid data',
                                    404: 'Not found',
                                    422: 'Invalid ethereum address'})
    def get(self, request, address, format=None):
        """
        Returns the history of a multisig tx (safe)
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        response = super().get(request, address)
        if response.data['count'] == 0:
            response.status_code = status.HTTP_404_NOT_FOUND

        return response

    @swagger_auto_schema(responses={202: 'Accepted',
                                    400: 'Invalid data',
                                    422: 'Invalid ethereum address/User is not an owner or tx not approved/executed'})
    def post(self, request, address, format=None):
        """
        Creates a Multisig Transaction with its confirmations and retrieves all the information related.
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        request.data['safe'] = address
        serializer = self.get_serializer_class()(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors)
        else:
            serializer.save()

            # Create task if transaction hash
            # data = serializer.validated_data
            # transaction_hash = data.get('transaction_hash')
            # if transaction_hash:
            #     check_approve_transaction_task.delay(safe_address=address,
            #                                          safe_tx_hash=data['contract_transaction_hash'].hex(),
            #                                          transaction_hash=transaction_hash.hex(),
            #                                          owner=data['sender'])

            return Response(status=status.HTTP_202_ACCEPTED)


class SafeBalanceView(APIView):
    serializer_class = SafeBalanceResponseSerializer

    @swagger_auto_schema(responses={200: SafeBalanceResponseSerializer(many=True),
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid'})
    def get(self, request, address, format=None):
        """
        Get status of the safe
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            safe_balances = BalanceServiceProvider().get_balances(address)
            serializer = self.serializer_class(data=safe_balances, many=True)
            serializer.is_valid()
            return Response(status=status.HTTP_200_OK, data=serializer.data)


class SafeIncomingTxListView(APIView):
    serializer_class = IncomingTransactionResponseSerializer

    @swagger_auto_schema(responses={200: IncomingTransactionResponseSerializer(many=True),
                                    404: 'Safe not found',
                                    422: 'Safe address checksum not valid'})
    def get(self, request, address, format=None):
        """
        Get status of the safe
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            try:
                SafeContract.objects.get(address=address)
            except SafeContract.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)

            incoming_txs = []
            for internal_tx in InternalTx.objects.filter(to=address,
                                                         call_type=EthereumTxCallType.CALL.value,
                                                         value__gt=0):
                incoming_txs.append({
                    'transaction_hash': internal_tx.ethereum_tx_id,
                    'to': internal_tx.to,
                    'from': internal_tx._from,
                    'value': internal_tx.value,
                    'token_address': None,
                })

            for ethereum_event in EthereumEvent.objects.erc20_events().filter(arguments__to=address):
                incoming_txs.append({
                    'transaction_hash': ethereum_event.ethereum_tx_id,
                    'to': ethereum_event.arguments['to'],
                    'from': ethereum_event.arguments['from'],
                    'value': ethereum_event.arguments['value'],
                    'token_address': ethereum_event.address,
                })

            serializer = self.serializer_class(data=incoming_txs, many=True)
            serializer.is_valid()
            return Response(status=status.HTTP_200_OK, data=serializer.data)
