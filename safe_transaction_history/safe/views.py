import ethereum.utils
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer


from safe_transaction_history.safe.models import MultisigTransaction
from safe_transaction_history.version import __version__
from .serializers import BaseSafeMultisigTransactionSerializer, SafeMultisigHistorySerializer
from .contracts import get_safe_team_contract
from .ethereum_service import EthereumServiceProvider


class AboutView(APIView):
    renderer_classes = (JSONRenderer,)

    def get(self, request, format=None):
        content = {
            'name': 'Safe Transaction History Service',
            'version': __version__,
            'api_version': self.request.version
        }
        return Response(content)


class SafeMultisigTransactionView(CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = BaseSafeMultisigTransactionSerializer

    def get(self, request, address, format=None):
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            multisig_transaction = MultisigTransaction.objects.get(safe=address)
        except MultisigTransaction.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = SafeMultisigHistorySerializer(multisig_transaction)
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    def post(self, request, address, format=None):
        if not ethereum.utils.check_checksum(address):
            return Response(status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        request.data['safe'] = address
        serializer = self.serializer_class(data=request.data)

        if serializer.is_valid():
            data = serializer.validated_data
            # check isOwnerAndConfirmed
            if self.is_owner_and_confirmed(data['safe'], data['contract_transaction_hash'], data['sender']):
                # Save data into Database
                serializer.save()
                return Response(status=status.HTTP_201_CREATED)
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST, data=serializer.errors)

    def is_owner_and_confirmed(self, safe_address, transaction_hash, owner) -> bool:
        ethereum_service = EthereumServiceProvider()
        w3 = ethereum_service.w3 # Web3 instance
        safe_contract = get_safe_team_contract(w3, address=safe_address)

        is_confirmed = safe_contract.functions.isApproved(transaction_hash, owner).call()
        return is_confirmed