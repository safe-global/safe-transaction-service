from django.conf.urls import url
from django.urls import path

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    url(r'^about/$', views.AboutView.as_view(), name='about'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTransactionListView.as_view(),
         name='multisig-transactions'),
    path('transactions/<str:tx_hash>', views.SafeMultisigTransactionDetailView.as_view(),
         name='multisig-transaction'),
]
