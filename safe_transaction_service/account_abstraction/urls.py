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
        "safes/<str:address>/safe-operations/",
        views.SafeOperationsView.as_view(),
        name="safe-operations",
    ),
]
