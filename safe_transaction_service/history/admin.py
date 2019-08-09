from django.contrib import admin

from .models import (EthereumBlock, EthereumEvent, EthereumTx, InternalTx,
                     InternalTxDecoded, MonitoredAddress, MultisigConfirmation,
                     MultisigTransaction)


@admin.register(MultisigConfirmation)
class MultisigConfirmationAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'multisig_transaction', 'transaction_hash', 'mined')
    list_filter = ('confirmation_type',)
    ordering = ['-created']
    search_fields = ['transaction_hash', 'owner']


@admin.register(MultisigTransaction)
class MultisigTransactionAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'safe', 'ethereum_tx_id', 'to', 'value', 'nonce', 'data')
    list_filter = ('operation',)
    ordering = ['-created']
    search_fields = ['=safe', '=ethereum_tx__tx_hash', 'to']


@admin.register(EthereumBlock)
class EthereumBlockAdmin(admin.ModelAdmin):
    date_hierarchy = 'timestamp'
    list_display = ('number', 'timestamp', 'gas_limit', 'gas_used', 'block_hash')
    search_fields = ['=number']
    ordering = ['-number']


@admin.register(EthereumEvent)
class EthereumEventAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx_id', 'log_index', 'data')


@admin.register(EthereumTx)
class EthereumTxAdmin(admin.ModelAdmin):
    list_display = ('block_id', 'tx_hash', 'nonce', 'from_', 'to')
    search_fields = ['=tx_hash', '=from_', '=to']
    ordering = ['-block_id']


@admin.register(InternalTx)
class InternalTxAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx_id', 'from_', 'to', 'value', 'call_type')
    list_filter = ('tx_type', 'call_type')
    search_fields = ['=ethereum_tx__block__number', '=from_', '=to']


@admin.register(InternalTxDecoded)
class InternalTxDecodedAdmin(admin.ModelAdmin):
    list_display = ('internal_tx_id', 'function_name', 'arguments', 'processed')
    list_filter = ('function_name', 'processed')
    search_fields = ['function_name', 'arguments']


@admin.register(MonitoredAddress)
class MonitoredAddressAdmin(admin.ModelAdmin):
    list_display = ('address', 'ethereum_tx_id', 'initial_block_number', 'tx_block_number', 'events_block_number')
    search_fields = ['address']
