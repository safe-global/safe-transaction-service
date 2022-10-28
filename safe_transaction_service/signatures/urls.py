from django.urls import path

from . import views

app_name = "contracts"

urlpatterns = [
    path("", views.ContractsView.as_view(), name="list"),
    path("safes/<str:address>/", views.ContractView.as_view(), name="detail"),
]
