from django.contrib import admin

from .models import Token


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ('address', 'trusted', 'name', 'symbol', 'decimals')
    list_filter = ('decimals', 'trusted')
    ordering = ('name',)
    search_fields = ['symbol', 'address', 'name']
