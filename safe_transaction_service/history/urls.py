from django.urls import path

from safe_transaction_service.contracts import views as contract_views
from safe_transaction_service.notifications import views as notification_views
from safe_transaction_service.tokens import views as token_views

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    path('about/', views.AboutView.as_view(), name='about'),
    path('about/master-copies/', views.MasterCopiesView.as_view(),
         name='master-copies'),
    path('analytics/multisig-transactions/by-safe/', views.AnalyticsMultisigTxsBySafeListView.as_view(),
         name='analytics-multisig-txs-by-safe'),
    path('analytics/multisig-transactions/by-origin/', views.AnalyticsMultisigTxsByOriginListView.as_view(),
         name='analytics-multisig-txs-by-origin'),
    path('safes/<str:address>/', views.SafeInfoView.as_view(),
         name='safe-info'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTransactionListView.as_view(),
         name='multisig-transactions-alias'),
    path('safes/<str:address>/multisig-transactions/', views.SafeMultisigTransactionListView.as_view(),
         name='multisig-transactions'),
    path('safes/<str:address>/multisig-transactions/estimations/', views.SafeMultisigTransactionEstimateView.as_view(),
         name='multisig-transaction-estimate'),
    path('safes/<str:address>/all-transactions/', views.AllTransactionsListView.as_view(),
         name='all-transactions'),
    path('safes/<str:address>/incoming-transfers/', views.SafeIncomingTransferListView.as_view(),
         name='incoming-transfers'),
    path('safes/<str:address>/transfers/', views.SafeTransferListView.as_view(),
         name='transfers'),
    path('safes/<str:address>/module-transactions/', views.SafeModuleTransactionListView.as_view(),
         name='module-transactions'),
    path('safes/<str:address>/creation/', views.SafeCreationView.as_view(),
         name='safe-creation'),
    path('safes/<str:address>/balances/', views.SafeBalanceView.as_view(),
         name='safe-balances'),
    path('safes/<str:address>/balances/usd/', views.SafeBalanceUsdView.as_view(),
         name='safe-balances-usd'),
    path('safes/<str:address>/collectibles/', views.SafeCollectiblesView.as_view(),
         name='safe-collectibles'),
    path('safes/<str:address>/delegates/', views.SafeDelegateListView.as_view(),
         name='safe-delegates'),
    path('safes/<str:address>/delegates/<str:delegate_address>/', views.SafeDelegateDestroyView.as_view(),
         name='safe-delegate'),
    path('transactions/<str:safe_tx_hash>/', views.SafeMultisigTransactionDetailView.as_view(),
         name='multisig-transaction-alias'),
    path('multisig-transactions/<str:safe_tx_hash>/', views.SafeMultisigTransactionDetailView.as_view(),
         name='multisig-transaction'),
    path('multisig-transactions/<str:safe_tx_hash>/confirmations/', views.SafeMultisigConfirmationsView.as_view(),
         name='multisig-transaction-confirmations'),
    path('owners/<str:address>/', views.OwnersView.as_view(),
         name='owners'),
    path('data-decoder/', views.DataDecoderView.as_view(),
         name='data-decoder'),

    # Contracts
    path('contracts/', contract_views.ContractsView.as_view(), name='contracts'),
    path('contracts/<str:address>/', contract_views.ContractView.as_view(), name='contract'),

    # Tokens
    path('tokens/', token_views.TokensView.as_view(), name='tokens'),
    path('tokens/<str:address>/', token_views.TokenView.as_view(), name='token'),

    # Notifications
    path('notifications/devices/', notification_views.FirebaseDeviceCreateView.as_view(),
         name='notifications-devices'),
    path('notifications/devices/<uuid:pk>/', notification_views.FirebaseDeviceDeleteView.as_view(),
         name='notifications-devices-delete'),
    path('notifications/devices/<uuid:pk>/safes/<str:address>/',
         notification_views.FirebaseDeviceSafeDeleteView.as_view(), name='notifications-devices-safes-delete'),

]
