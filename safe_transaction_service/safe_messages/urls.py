from django.urls import path

from . import views

app_name = "safe_messages"

urlpatterns = [
    path("<int:id>/", views.SafeMessageView.as_view(), name="detail"),
    path("safes/<str:address>/", views.SafeMessagesView.as_view(), name="list"),
]
