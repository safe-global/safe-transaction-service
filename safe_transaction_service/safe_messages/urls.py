from django.urls import include, path

from . import views

app_name = "safe_messages"

extra_patterns = [
    path("<str:message_hash>/", views.SafeMessageView.as_view(), name="message"),
    path(
        "<str:message_hash>/signatures/",
        views.SafeMessageSignatureView.as_view(),
        name="signatures",
    ),
]

urlpatterns = [
    path("messages/", include(extra_patterns)),
    path(
        "safes/<str:address>/messages/",
        views.SafeMessagesView.as_view(),
        name="safe-messages",
    ),
]
