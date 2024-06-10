from django.urls import path

from . import views

app_name = "account_abstraction"

urlpatterns = [
    path(
        "safe-operations/<str:safe_operation_hash>/",
        views.SafeOperationView.as_view(),
        name="safe-operation",
    ),
    path(
        "safe-operations/<str:safe_operation_hash>/confirmations/",
        views.SafeOperationConfirmationsView.as_view(),
        name="safe-operation-confirmations",
    ),
    path(
        "safes/<str:address>/safe-operations/",
        views.SafeOperationsView.as_view(),
        name="safe-operations",
    ),
    path(
        "user-operations/<str:user_operation_hash>/",
        views.UserOperationView.as_view(),
        name="user-operation",
    ),
    path(
        "safes/<str:address>/user-operations/",
        views.UserOperationsView.as_view(),
        name="user-operations",
    ),
]
