from django.urls import path

from . import views

app_name = "safe_messages"

urlpatterns = [
    path("<int:id>/", views.SafeMessageView.as_view(), name="message"),
    path(
        "<int:id>/signatures/",
        views.SafeMessageSignatureView.as_view(),
        name="signatures",
    ),
    path(
        "safes/<str:address>/", views.SafeMessagesView.as_view(), name="safe-messages"
    ),
]
