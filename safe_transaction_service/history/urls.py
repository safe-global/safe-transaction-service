from django.urls import path

from safe_transaction_service.tokens.views import TokensView, TokenView

from . import views
from safe_transaction_service.notifications.views import FirebaseDeviceCreateView

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    path('about/', views.AboutView.as_view(), name='about'),
    path('about/master-copies/', views.MasterCopiesView.as_view(),
         name='master-copies'),
    path('safes/<str:address>/', views.SafeInfoView.as_view(),
         name='safe-info'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTransactionListView.as_view(),
         name='multisig-transactions'),  # DEPRECATED, use `multisig-transactions`
    path('safes/<str:address>/multisig-transactions/', views.SafeMultisigTransactionListView.as_view(),
         name='multisig-transactions-alias'),
    path('safes/<str:address>/all-transactions/', views.AllTransactionsListView.as_view(),
         name='all-transactions'),
    path('safes/<str:address>/incoming-transactions/', views.SafeIncomingTransferListView.as_view(),
         name='incoming-transactions'),  # DEPRECATED, use `incoming-transfers`
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
         name='multisig-transaction'),
    path('owners/<str:address>/', views.OwnersView.as_view(),
         name='owners'),

    # Tokens
    path('tokens/', TokensView.as_view(), name='tokens'),
    path('tokens/<str:address>/', TokenView.as_view(), name='token'),

    # Notifications
    path('safes/<str:address>/notifications/devices/', FirebaseDeviceCreateView.as_view(),
         name='notifications-devices'),

]
