import ethereum.utils
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from safe_transaction_service.history.models import MultisigTransaction
from safe_transaction_service.version import __version__

from .filters import DefaultPagination
from .serializers import (SafeMultisigHistoryResponseSerializer,
                          SafeMultisigTransactionHistorySerializer)
from .tasks import check_approve_transaction_task


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
            'secure': self.request.is_secure()
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
        try:
            if not ethereum.utils.check_checksum(address):
                raise ValueError
        except ValueError:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        multisig_transactions = MultisigTransaction.objects.filter(safe=address)

        if multisig_transactions.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Check if the 'owners' query parameter was passed in input
        owners = None
        query_owners = self.request.query_params.get('owners', None)
        if query_owners:
            owners = [owner for owner in query_owners.split(',') if owner != '']

        serializer = self.get_serializer(multisig_transactions, many=True, owners=owners)
        # Paginate results
        page = self.paginate_queryset(serializer.data)
        pagination = self.get_paginated_response(page)
        return Response(status=status.HTTP_200_OK, data=pagination.data)

    @swagger_auto_schema(responses={202: 'Accepted',
                                    400: 'Invalid data',
                                    422: 'Invalid ethereum address/User is not an owner or tx not approved/executed'})
    def post(self, request, address, format=None):
        """
        Creates a Multisig Transaction with its confirmations and retrieves all the information related.
        """
        try:
            if not ethereum.utils.check_checksum(address):
                raise ValueError
        except ValueError:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        request.data['safe'] = address
        serializer = self.get_serializer_class()(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=serializer.errors)
        else:
            serializer.save()

            # Create task if transaction hash
            data = serializer.validated_data
            transaction_hash = data.get('transaction_hash')
            if transaction_hash:
                check_approve_transaction_task.delay(safe_address=address,
                                                     safe_tx_hash=data['contract_transaction_hash'].hex(),
                                                     transaction_hash=transaction_hash.hex(),
                                                     owner=data['sender'])

            return Response(status=status.HTTP_202_ACCEPTED)
