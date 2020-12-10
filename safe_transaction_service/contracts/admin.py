from django.contrib import admin

from .models import Contract, ContractAbi


@admin.register(ContractAbi)
class ContractAbiAdmin(admin.ModelAdmin):
    list_display = ('description', 'abi')


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('address', 'name', 'has_abi')
    ordering = ['address']
    raw_id_fields = ('contract_abi',)
    search_fields = ['address', 'name', 'contract_abi__abi', 'contract_abi__description']

    def has_abi(self, obj: Contract) -> bool:
        return obj.contract_abi_id is not None
    has_abi.boolean = True
