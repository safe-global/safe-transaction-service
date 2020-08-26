from typing import Iterable

from django.contrib import admin

from .models import FirebaseDevice


@admin.register(FirebaseDevice)
class FirebaseDeviceAdmin(admin.ModelAdmin):
    list_display = ('uuid', 'cloud_messaging_token', 'device_type', 'version', 'safe_addresses')
    list_filter = ('device_type', 'version', 'bundle')
    ordering = ['uuid']
    raw_id_fields = ('safes',)
    search_fields = ['uuid', 'cloud_messaging_token', 'safes__address']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related('safes')

    def safe_addresses(self, obj: FirebaseDevice) -> Iterable[str]:
        return [safe.address for safe in obj.safes.all()]
