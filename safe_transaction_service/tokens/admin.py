from django.contrib import admin

from safe_transaction_service.utils.admin import (
    AdvancedAdminSearchMixin,
    HasLogoFilterAdmin,
)

from .models import Token, TokenList


@admin.register(Token)
class TokenAdmin(AdvancedAdminSearchMixin, admin.ModelAdmin):
    list_display = (
        "address",
        "trusted",
        "spam",
        "events_bugged",
        "name",
        "symbol",
        "decimals",
        "copy_price",
    )
    list_filter = ("trusted", "spam", "events_bugged", "decimals", HasLogoFilterAdmin)
    ordering = ("address",)
    search_fields = ["==address", "symbol", "name", "==copy_price"]


@admin.register(TokenList)
class TokenListAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "url",
        "description",
    )
    ordering = ("pk",)
    search_fields = ["url", "description"]
