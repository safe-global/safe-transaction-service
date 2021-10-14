from django.contrib import admin

from .models import Token


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = (
        "address",
        "trusted",
        "spam",
        "events_bugged",
        "name",
        "symbol",
        "decimals",
    )
    list_filter = ("trusted", "spam", "events_bugged", "decimals")
    ordering = ("name",)
    search_fields = ["symbol", "address", "name"]
