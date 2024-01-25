from typing import List

from django.contrib import admin

from safe_transaction_service.utils.admin import AdvancedAdminSearchMixin

from .models import FirebaseDevice, FirebaseDeviceOwner


@admin.register(FirebaseDevice)
class FirebaseDeviceAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = (
        "uuid",
        "cloud_messaging_token",
        "device_type",
        "version",
        "safe_addresses",
    )
    list_filter = ("device_type", "version", "bundle")
    ordering = ["uuid"]
    raw_id_fields = ("safes",)
    readonly_fields = ("owners",)
    search_fields = ["==uuid", "==cloud_messaging_token", "==safes__address"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("safes")

    def owners(self, obj: FirebaseDevice) -> List[str]:
        return list(obj.owners.values_list("owner", flat=True))

    def safe_addresses(self, obj: FirebaseDevice) -> List[str]:
        return list(obj.safes.values_list("address", flat=True))


@admin.register(FirebaseDeviceOwner)
class FirebaseDeviceOwnerAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = ("firebase_device_id", "owner")
    ordering = ["firebase_device_id"]
    search_fields = [
        "==firebase_device_id__uuid",
        "==owner",
    ]
