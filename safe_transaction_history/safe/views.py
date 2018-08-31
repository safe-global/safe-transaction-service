import datetime

import ethereum.utils
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from safe_transaction_history.safe.models import MultisigTransaction
from safe_transaction_history.version import __version__

from gnosis.safe.contracts import get_safe_owner_manager_contract, get_safe_team_contract
from gnosis.safe.ethereum_service import EthereumServiceProvider
from .filters import DefaultPagination
from .serializers import (SafeMultisigHistorySerializer,
                          SafeMultisigTransactionSerializer)
from .tasks import check_approve_transaction


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
    permission_classes = (AllowAny,)
    pagination_class = DefaultPagination

    def get_serializer_class(self):
        """
        Proxy returning a serializer class according to the request's verb.
        """
        if self.request.method == 'GET':
            return SafeMultisigHistorySerializer
        elif self.request.method == 'POST':
            return SafeMultisigTransactionSerializer

    @swagger_auto_schema(responses={400: 'Invalid data',
                                    422: 'Invalid ethereum address'})
    def get(self, request, address, format=None):
        """
        Returns the history of a multisig (safe)
        """
        try:
            if not ethereum.utils.check_checksum(address):
                raise Exception
        except Exception:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        multisig_transactions = MultisigTransaction.objects.filter(safe=address)

        if multisig_transactions.count() == 0:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Check if the 'owners' query parameter was passed in input
        owners = None
        query_owners = self.request.query_params.get('owners', None)
        if query_owners:
            owners = [owner for owner in query_owners.split(',') if owner != '']

        serializer = self.get_serializer_class()(multisig_transactions, many=True, owners=owners)
        # Paginate results
        page = self.paginate_queryset(serializer.data)
        pagination = self.get_paginated_response(page)
        return Response(status=status.HTTP_200_OK, data=pagination.data)

    @swagger_auto_schema(responses={202: 'Accepted',
                                    400: 'Invalid data',
                                    422: 'Invalid ethereum address/User is not an owner or tx not approved/executed'})
    def post(self, request, address, format=None):
        """
        Allows to create a multisig transaction with its confirmations and to retrieve all the information related with
        a Safe.
        """
        try:
            if not ethereum.utils.check_checksum(address):
                raise Exception
        except Exception:
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY, data='Invalid ethereum address')

        request.data['safe'] = address

        # Get block_number and block_date_time from transaction_hash
        if 'transaction_hash' in request.data:
            try:
                ethereum_service = EthereumServiceProvider()
                transaction_data = ethereum_service.get_transaction(request.data['transaction_hash'])
                if transaction_data:
                    tx_block_number = transaction_data['blockNumber']
                    block_data = ethereum_service.get_block(tx_block_number)
                    block_date_time = datetime.datetime.utcfromtimestamp(block_data['timestamp'])
                    request.data['block_number'] = tx_block_number
                    request.data['block_date_time'] = block_date_time
                else:
                    raise ValueError
            except ValueError:
                return Response(status=status.HTTP_400_BAD_REQUEST, data='Cannot get info from transaction_hash %s' %
                                                                         request.data['transaction_hash'])

        serializer = self.get_serializer_class()(data=request.data)

        if not serializer.is_valid():
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)
        else:
            data = serializer.validated_data
            contract_transaction_hash = data['contract_transaction_hash'].hex()
            transaction_hash = data['transaction_hash'].hex()
            sender = data['sender']
            # check isOwnerAndConfirmed
            if (self.is_owner_and_confirmed(address, contract_transaction_hash, sender)
                    or self.is_owner_and_executed(address, contract_transaction_hash, sender)):
                # Save data into Database
                serializer.save()

                # Create task
                check_approve_transaction.delay(safe_address=address,
                                                contract_transaction_hash=contract_transaction_hash,
                                                transaction_hash=transaction_hash,
                                                owner=sender)

                return Response(status=status.HTTP_202_ACCEPTED)
            else:
                return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                data='User is not an owner or tx not approved/executed')

    # TODO Refactor this, these methods should be on SafeService
    def is_owner_and_confirmed(self, safe_address: str, contract_transaction_hash: str, owner: str) -> bool:
        """
        Checks whether an account (owner) is one of the Safe's owners and the incoming contract_transaction_hash
        was approved
        """
        ethereum_service = EthereumServiceProvider()
        w3 = ethereum_service.w3  # Web3 instance
        safe_owner_contract = get_safe_owner_manager_contract(w3, safe_address)
        safe_contract = get_safe_team_contract(w3, safe_address)

        is_owner = safe_owner_contract.functions.isOwner(owner).call()
        is_approved = safe_contract.functions.isApproved(contract_transaction_hash, owner).call()
        return is_owner and is_approved

    def is_owner_and_executed(self, safe_address: str, contract_transaction_hash: str, owner: str) -> bool:
        """
        Checks whether an account (owner) is one of the Safe's owners and the incoming contract_transaction_hash
        was executed
        """
        ethereum_service = EthereumServiceProvider()
        w3 = ethereum_service.w3  # Web3 instance
        safe_owner_contract = get_safe_owner_manager_contract(w3, safe_address)
        safe_contract = get_safe_team_contract(w3, safe_address)

        is_owner = safe_owner_contract.functions.isOwner(owner).call()
        is_executed = safe_contract.functions.isExecuted(contract_transaction_hash).call()

        return is_owner and is_executed
