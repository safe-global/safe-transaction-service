from django.urls import path

from . import views_v2

app_name = "history"

urlpatterns = [
    path(
        "safes/<str:address>/collectibles/",
        views_v2.SafeCollectiblesView.as_view(),
        name="safe-collectibles",
    ),
    path("delegates/", views_v2.DelegateListView.as_view(), name="delegates"),
    path(
        "delegates/<str:delegate_address>/",
        views_v2.DelegateDeleteView.as_view(),
        name="delegate",
    ),
    path(
        "safes/<str:address>/balances/",
        views_v2.SafeBalanceView.as_view(),
        name="safe-balances",
    ),
]
