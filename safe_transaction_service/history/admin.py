from django.contrib import admin

from .models import (EthereumBlock, EthereumEvent, EthereumTx, InternalTx,
                     InternalTxDecoded, MonitoredAddress, MultisigConfirmation,
                     MultisigTransaction, SafeStatus)


@admin.register(MultisigConfirmation)
class MultisigConfirmationAdmin(admin.ModelAdmin):
    list_display = ('multisig_transaction', 'transaction_hash', 'owner')
    search_fields = ['transaction_hash', 'owner']


@admin.register(MultisigTransaction)
class MultisigTransactionAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'safe', 'mined', 'ethereum_tx_id', 'to', 'value', 'nonce', 'data')
    ordering = ['-created']
    search_fields = ['=safe', '=ethereum_tx_id', 'to']


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
    list_display = ('block_id', 'tx_hash', 'nonce', '_from', 'to')
    search_fields = ['=tx_hash', '=_from', '=to']
    ordering = ['-block_id']


@admin.register(InternalTx)
class InternalTxAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx_id', '_from', 'to', 'value', 'call_type')
    list_filter = ('tx_type', 'call_type')
    search_fields = ['=ethereum_tx__block__number', '=_from', '=to']


@admin.register(InternalTxDecoded)
class InternalTxDecodedAdmin(admin.ModelAdmin):
    list_display = ('internal_tx_id', 'function_name', 'arguments', 'processed')
    list_filter = ('function_name', 'processed')
    search_fields = ['function_name', 'arguments']


@admin.register(MonitoredAddress)
class MonitoredAddressAdmin(admin.ModelAdmin):
    list_display = ('address', 'ethereum_tx_id', 'initial_block_number', 'tx_block_number', 'events_block_number')
    search_fields = ['address']


@admin.register(SafeStatus)
class SafeStatusAdmin(admin.ModelAdmin):
    list_display = ('internal_tx_decoded_id', 'address', 'owners', 'threshold')
    list_filter = ('threshold',)
    search_fields = ['address', 'owners']
