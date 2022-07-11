from django.urls import path

from . import views_v2

app_name = "history"

urlpatterns = [
    path(
        "safes/<str:address>/collectibles/",
        views_v2.SafeCollectiblesView.as_view(),
        name="safe-collectibles",
    ),
]
