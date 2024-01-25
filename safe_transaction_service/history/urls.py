from django.urls import path

from . import views

app_name = "history"

urlpatterns = [
    path("about/", views.AboutView.as_view(), name="about"),
    path(
        "about/ethereum-rpc/",
        views.AboutEthereumRPCView.as_view(),
        name="about-ethereum-rpc",
    ),
    path(
        "about/ethereum-tracing-rpc/",
        views.AboutEthereumTracingRPCView.as_view(),
        name="about-ethereum-tracing-rpc",
    ),
    path(
        "about/master-copies/", views.MasterCopiesView.as_view(), name="master-copies"
    ),  # Deprecated
    path("about/singletons/", views.SingletonsView.as_view(), name="singletons"),
    path(
        "about/indexing/",
        views.IndexingView.as_view(),
        name="indexing",
    ),
    path("data-decoder/", views.DataDecoderView.as_view(), name="data-decoder"),
    path("delegates/", views.DelegateListView.as_view(), name="delegates"),
    path(
        "delegates/<str:delegate_address>/",
        views.DelegateDeleteView.as_view(),
        name="delegate",
    ),
    path("safes/<str:address>/", views.SafeInfoView.as_view(), name="safe-info"),
    path(
        "safes/<str:address>/transactions/",
        views.SafeMultisigTransactionDeprecatedListView.as_view(),
        name="multisig-transactions-alias",
    ),
    path(
        "safes/<str:address>/multisig-transactions/",
        views.SafeMultisigTransactionListView.as_view(),
        name="multisig-transactions",
    ),
    path(
        "safes/<str:address>/multisig-transactions/estimations/",
        views.SafeMultisigTransactionEstimateView.as_view(),
        name="multisig-transaction-estimate",
    ),
    path(
        "safes/<str:address>/all-transactions/",
        views.AllTransactionsListView.as_view(),
        name="all-transactions",
    ),
    path(
        "safes/<str:address>/incoming-transfers/",
        views.SafeIncomingTransferListView.as_view(),
        name="incoming-transfers",
    ),
    path(
        "safes/<str:address>/transfers/",
        views.SafeTransferListView.as_view(),
        name="transfers",
    ),
    path(
        "transfer/<str:transfer_id>",
        views.TransferView.as_view(),
        name="transfer",
    ),
    path(
        "module-transaction/<str:module_transaction_id>",
        views.ModuleTransactionView.as_view(),
        name="module-transaction",
    ),
    path(
        "safes/<str:address>/module-transactions/",
        views.SafeModuleTransactionListView.as_view(),
        name="module-transactions",
    ),
    path(
        "safes/<str:address>/creation/",
        views.SafeCreationView.as_view(),
        name="safe-creation",
    ),
    path(
        "safes/<str:address>/balances/",
        views.SafeBalanceView.as_view(),
        name="safe-balances",
    ),
    path(
        "safes/<str:address>/balances/usd/",
        views.SafeBalanceUsdView.as_view(),
        name="safe-balances-usd",
    ),
    path(
        "safes/<str:address>/delegates/<str:delegate_address>/",
        views.SafeDelegateDestroyView.as_view(),
        name="safe-delegate",
    ),
    path(
        "multisig-transactions/<str:safe_tx_hash>/",
        views.SafeMultisigTransactionDetailView.as_view(),
        name="multisig-transaction",
    ),
    path(
        "multisig-transactions/<str:safe_tx_hash>/confirmations/",
        views.SafeMultisigConfirmationsView.as_view(),
        name="multisig-transaction-confirmations",
    ),
    path("modules/<str:address>/safes/", views.ModulesView.as_view(), name="modules"),
    path("owners/<str:address>/safes/", views.OwnersView.as_view(), name="owners"),
    path(
        "transactions/<str:safe_tx_hash>/",
        views.SafeMultisigTransactionDeprecatedDetailView.as_view(),
        name="multisig-transaction-alias",
    ),
]
