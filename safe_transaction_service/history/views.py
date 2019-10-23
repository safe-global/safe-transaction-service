from django.conf import settings

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from web3 import Web3

from safe_transaction_service.history.models import MultisigTransaction
from safe_transaction_service.version import __version__

from .filters import DefaultPagination
from .serializers import (SafeMultisigHistoryResponseSerializer,
                          SafeMultisigTransactionHistorySerializer)


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
                'INTERNAL_TXS_BLOCK_PROCESS_LIMIT ': settings.INTERNAL_TXS_BLOCK_PROCESS_LIMIT,
                'SAFE_CONTRACT_ADDRESS': settings.SAFE_CONTRACT_ADDRESS,
                'SAFE_VALID_CONTRACT_ADDRESSES': settings.SAFE_VALID_CONTRACT_ADDRESSES,
                'SAFE_REORG_BLOCKS': settings.SAFE_REORG_BLOCKS,
                'SAFE_PROXY_FACTORY_ADDRESS': settings.SAFE_PROXY_FACTORY_ADDRESS,
            }
        }
        return Response(content)


class SafeMultisigTransactionListView(ListAPIView):
    pagination_class = DefaultPagination

    def get_serializer_class(self):
        """
        Proxy returning a serializer class according to the request's verb.
        """
        if self.request.method == 'GET':
            return SafeMultisigHistoryResponseSerializer
        elif self.request.method == 'POST':
            return SafeMultisigTransactionHistorySerializer

    @swagger_auto_schema(responses={400: 'Invalid data',
                                    422: 'Invalid ethereum address'})
    def get(self, request, address, format=None):
        """
        Returns the history of a multisig tx (safe)
        """
        if not Web3.isChecksumAddress(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        multisig_transactions = MultisigTransaction.objects.filter(
            safe=address
        ).prefetch_related(
            'confirmations'
        ).select_related(
            'ethereum_tx'
        ).order_by(
            '-nonce'
        )

        # Check if the 'owners' query parameter was passed in input
        query_owners = self.request.query_params.get('owners', None)
        owners = [owner for owner in query_owners.split(',') if owner != ''] if query_owners else None

        serializer = self.get_serializer(multisig_transactions, many=True, owners=owners)
        # Paginate results
        page = self.paginate_queryset(serializer.data)
        if not page:
            return Response(status=status.HTTP_404_NOT_FOUND)

        pagination = self.get_paginated_response(page)
        return Response(status=status.HTTP_200_OK, data=pagination.data)

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
