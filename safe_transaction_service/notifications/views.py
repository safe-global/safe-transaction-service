from rest_framework.generics import CreateAPIView, DestroyAPIView

from .models import FirebaseDevice
from .serializers import FirebaseDeviceSerializer


class FirebaseDeviceCreateView(CreateAPIView):
    serializer_class = FirebaseDeviceSerializer


class FirebaseDeviceDeleteView(DestroyAPIView):
    queryset = FirebaseDevice.objects.all()
