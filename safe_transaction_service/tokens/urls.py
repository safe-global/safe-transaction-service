from django.urls import path

from . import views

app_name = "tokens"

urlpatterns = [
    path("", views.TokensView.as_view(), name="list"),
    path("<str:address>/", views.TokenView.as_view(), name="detail"),
]
