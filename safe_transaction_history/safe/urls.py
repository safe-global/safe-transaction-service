from django.conf.urls import url
from django.urls import path

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    url(r'^about/$', views.AboutView.as_view(), name='about'),
    path('safes/<str:address>/transaction/', views.SafeMultisigTransactionView.as_view(), name='create-multisig-transactions'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTransactionView.as_view(), name='get-multisig-transactions'),
]
