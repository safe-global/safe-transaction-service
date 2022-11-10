from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path(
        "multisig-transactions/by-safe/",
        views.AnalyticsMultisigTxsBySafeListView.as_view(),
        name="analytics-multisig-txs-by-safe",
    ),
    path(
        "multisig-transactions/by-origin/",
        views.AnalyticsMultisigTxsByOriginListView.as_view(),
        name="analytics-multisig-txs-by-origin",
    ),
]
