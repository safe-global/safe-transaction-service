# SPDX-License-Identifier: FSL-1.1-MIT
from django.urls import path

from . import views_v2

app_name = "policies"

urlpatterns = [
    path(
        "safes/<str:address>/policy-confirmations/",
        views_v2.SafePolicyConfirmationsView.as_view(),
        name="policy-confirmations",
    ),
    path(
        "safes/<str:address>/policy-root-requests/",
        views_v2.SafePolicyRootRequestsView.as_view(),
        name="policy-root-requests",
    ),
]
