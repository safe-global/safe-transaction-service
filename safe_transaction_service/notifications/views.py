from rest_framework.generics import CreateAPIView

from .serializers import FirebaseDeviceSerializer


class FirebaseDeviceCreateView(CreateAPIView):
    serializer_class = FirebaseDeviceSerializer
