from typing import Optional

from django.contrib import admin

from .models import (EthereumBlock, EthereumEvent, EthereumTx, InternalTx,
                     InternalTxDecoded, MonitoredAddress, MultisigConfirmation,
                     MultisigTransaction, SafeStatus, ProxyFactory, SafeContract, SafeMasterCopy)


@admin.register(EthereumBlock)
class EthereumBlockAdmin(admin.ModelAdmin):
    date_hierarchy = 'timestamp'
    list_display = ('number', 'timestamp', 'confirmed', 'gas_limit', 'gas_used', 'block_hash')
    search_fields = ['=number']
    ordering = ['-number']


@admin.register(EthereumEvent)
class EthereumEventAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx_id', 'log_index', 'data')


@admin.register(EthereumTx)
class EthereumTxAdmin(admin.ModelAdmin):
    list_display = ('block_id', 'tx_hash', 'nonce', '_from', 'to')
    search_fields = ['=tx_hash', '=_from', '=to']
    ordering = ['-block_id']


@admin.register(InternalTx)
class InternalTxAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx_id', 'block_number', '_from', 'to', 'value', 'call_type', 'trace_address')
    list_filter = ('tx_type', 'call_type')
    list_select_related = ('ethereum_tx',)
    search_fields = ['=ethereum_tx__block__number', '=_from', '=to']
    ordering = ['-ethereum_tx__block_id', 'trace_address']


@admin.register(InternalTxDecoded)
class InternalTxDecodedAdmin(admin.ModelAdmin):
    list_display = ('block_number', 'internal_tx_id', 'processed', 'address', 'function_name', 'arguments')
    list_filter = ('function_name', 'processed')
    ordering = ['-internal_tx__ethereum_tx__block_id',
                '-internal_tx__ethereum_tx__transaction_index',
                '-internal_tx_id']
    list_select_related = ('internal_tx__ethereum_tx',)
    search_fields = ['function_name', 'arguments', '=internal_tx__to']


@admin.register(MultisigConfirmation)
class MultisigConfirmationAdmin(admin.ModelAdmin):
    list_display = ('multisig_transaction_hash', 'multisig_transaction_id', 'ethereum_tx_id', 'owner')
    search_fields = ['=ethereum_tx__tx_hash', '=multisig_transaction_hash', '=owner']


@admin.register(MultisigTransaction)
class MultisigTransactionAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'safe', 'executed', 'ethereum_tx_id', 'to', 'value', 'nonce', 'data')
    list_select_related = ('ethereum_tx',)
    ordering = ['-created']
    search_fields = ['=ethereum_tx__tx_hash', '=safe', 'to']

    def executed(self, obj: MultisigTransaction):
        return obj.executed
    executed.boolean = True


class MonitoredAddressAdmin(admin.ModelAdmin):
    list_display = ('address', 'initial_block_number', 'tx_block_number')
    search_fields = ['address']


@admin.register(SafeMasterCopy)
class SafeMasterCopyAdmin(MonitoredAddressAdmin):
    pass


@admin.register(ProxyFactory)
class ProxyFactoryAdmin(MonitoredAddressAdmin):
    pass


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    list_display = ('created_block_number', 'address', 'ethereum_tx_id')
    list_select_related = ('ethereum_tx',)
    ordering = ['-ethereum_tx__block_id']
    search_fields = ['address']

    def created_block_number(self, obj: SafeContract) -> Optional[int]:
        if obj.ethereum_tx:
            return obj.ethereum_tx.block_id


@admin.register(SafeStatus)
class SafeStatusAdmin(admin.ModelAdmin):
    list_display = ('block_number', 'internal_tx_id', 'address', 'owners', 'threshold', 'nonce', 'master_copy')
    list_filter = ('threshold',)
    list_select_related = ('internal_tx__ethereum_tx',)
    ordering = ['-internal_tx__ethereum_tx__block_id', '-internal_tx_id']
    search_fields = ['address', 'owners']
