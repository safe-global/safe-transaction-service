import datetime

import ethereum.utils
from rest_framework import status
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer

from safe_transaction_history.safe.models import MultisigTransaction
from safe_transaction_history.version import __version__
from .serializers import SafeMultisigTransactionSerializer, SafeMultisigHistorySerializer
from .contracts import get_safe_team_contract, get_safe_owner_manager_contract
from .ethereum_service import EthereumServiceProvider
from .tasks import check_approve_transaction
from .filters import DefaultPagination


class AboutView(APIView):
    """
    Returns info about the project.
    """
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        content = {
            'name': 'Safe Transaction History Service',
            'version': __version__,
            'api_version': self.request.version,
            'secure': self.request.is_secure()
        }
        return Response(content)


class SafeMultisigTransactionListView(ListAPIView):
    """
    Returns the history of a multisig (safe)
    """
    permission_classes = (AllowAny,)
    serializer_class = SafeMultisigHistorySerializer
    pagination_class = DefaultPagination

    def get(self, request, address, format=None):
        try:
            if not ethereum.utils.check_checksum(address):
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        multisig_transactions = MultisigTransaction.objects.filter(safe=address)

        if multisig_transactions.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Check if the 'owners' query parameter was passed in input
        owners = None
        query_owners = self.request.query_params.get('owners', None)
        if query_owners:
            owners = [owner for owner in query_owners.split(',') if owner != '']

        serializer = self.serializer_class(multisig_transactions, many=True, owners=owners)
        # Paginate results
        page = self.paginate_queryset(serializer.data)
        pagination = self.get_paginated_response(page)
        return Response(status=status.HTTP_200_OK, data=pagination.data)


class SafeMultisigTransactionView(CreateAPIView):
    """
    Allows to create a multisig transaction with its confirmations and to retrieve all the information related with
    a Safe.
    """
    permission_classes = (AllowAny,)
    serializer_class = SafeMultisigTransactionSerializer

    def post(self, request, address, format=None):
        try:
            if not ethereum.utils.check_checksum(address):
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ValueError:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if 'transaction_hash' in request.data:
            try:
                ethereum_service = EthereumServiceProvider()
                transaction_data = ethereum_service.get_transaction(request.data['transaction_hash'])
                if transaction_data:
                    tx_block_number = transaction_data['blockNumber']
                    block_data = ethereum_service.get_block(tx_block_number)
                    block_date_time = datetime.datetime.fromtimestamp(block_data['timestamp'])
                    request.data['block_number'] = tx_block_number
                    request.data['block_date_time'] = block_date_time
            except ValueError:
                return Response(status=status.HTTP_400_BAD_REQUEST)

        request.data['safe'] = address
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data
            # check isOwnerAndConfirmed
            if self.is_owner_and_confirmed(data['safe'], data['contract_transaction_hash'], data['sender']) \
                    or self.is_owner_and_executed(data['safe'], data['contract_transaction_hash'], data['sender']):
                # Save data into Database
                serializer.save()

                # Create task
                check_approve_transaction.delay(safe_address=address,
                                                contract_transaction_hash=data['contract_transaction_hash'],
                                                transaction_hash=data['transaction_hash'],
                                                owner=data['sender'])

                return Response(status=status.HTTP_202_ACCEPTED)
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)

    def is_owner_and_confirmed(self, safe_address, contract_transaction_hash, owner) -> bool:
        ethereum_service = EthereumServiceProvider()
        w3 = ethereum_service.w3 # Web3 instance
        safe_owner_contract = get_safe_owner_manager_contract(w3, safe_address)
        safe_contract = get_safe_team_contract(w3, safe_address)

        is_owner = safe_owner_contract.functions.isOwner(owner).call()
        is_approved = safe_contract.functions.isApproved(contract_transaction_hash, owner).call()
        return is_owner and is_approved

    def is_owner_and_executed(self, safe_address, transaction_hash, owner) -> bool:
        ethereum_service = EthereumServiceProvider()
        w3 = ethereum_service.w3 # Web3 instance
        safe_owner_contract = get_safe_owner_manager_contract(w3, safe_address)
        safe_contract = get_safe_team_contract(w3, safe_address)

        is_owner = safe_owner_contract.functions.isOwner(owner).call()
        is_executed = safe_contract.functions.isExecuted(transaction_hash).call()

        return is_owner and is_executed
