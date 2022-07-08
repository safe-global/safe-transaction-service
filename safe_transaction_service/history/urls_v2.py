from django.urls import path

from . import views

app_name = "history"

urlpatterns = [
    path(
        "safes/<str:address>/collectibles/",
        views.SafeCollectiblesViewV2.as_view(),
        name="safe-collectibles",
    ),
]
