from django.urls import path

from . import views

app_name = "tokens"

urlpatterns = [
    path('', views.TokensView.as_view(), name='tokens'),
]
