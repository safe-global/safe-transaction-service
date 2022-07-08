from django.urls import path

from . import views

app_name = "historyV2"

urlpatterns = [
    path(
        "safes/<str:address>/collectibles/",
        views.SafeCollectiblesViewV2.as_view(),
        name="safe-collectibles",
    ),
]
