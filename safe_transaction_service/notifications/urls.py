from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("devices/", views.FirebaseDeviceCreateView.as_view(), name="devices"),
    path(
        "devices/<uuid:pk>/",
        views.FirebaseDeviceDeleteView.as_view(),
        name="devices-delete",
    ),
    path(
        "devices/<uuid:pk>/safes/<str:address>/",
        views.FirebaseDeviceSafeDeleteView.as_view(),
        name="devices-safes-delete",
    ),
]
