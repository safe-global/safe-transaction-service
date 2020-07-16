from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response

from safe_transaction_service.history.decorators import \
    ethereum_address_checksum_validator
from safe_transaction_service.history.models import SafeContract

from .serializers import FirebaseDeviceSerializer


class FirebaseDeviceCreateView(CreateAPIView):
    serializer_class = FirebaseDeviceSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['safe'] = self.kwargs['address']
        return context

    @ethereum_address_checksum_validator
    def post(self, request, address, *args, **kwargs):
        """
        Get status of the safe
        """

        if not SafeContract.objects.filter(address=address).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        return super().post(request, address, *args, **kwargs)
