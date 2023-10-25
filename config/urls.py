from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, re_path
from django.views import defaults as default_views

from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

schema_view = get_schema_view(
    openapi.Info(
        title="Safe Transaction Service API",
        default_version="v1",
        description="API to keep track of transactions sent via Safe smart contracts",
        license=openapi.License(name="MIT License"),
    ),
    validators=["flex", "ssv"],
    public=True,
    permission_classes=[permissions.AllowAny],
)

schema_cache_timeout = 60 * 5  # 5 minutes

swagger_urlpatterns = [
    path(
        "",
        schema_view.with_ui("swagger", cache_timeout=schema_cache_timeout),
        name="schema-swagger-ui",
    ),
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=schema_cache_timeout),
        name="schema-json",
    ),
    path(
        "redoc/",
        schema_view.with_ui("redoc", cache_timeout=schema_cache_timeout),
        name="schema-redoc",
    ),
]

urlpatterns_v1 = [
    path("", include("safe_transaction_service.history.urls", namespace="history")),
    path(
        "contracts/",
        include("safe_transaction_service.contracts.urls", namespace="contracts"),
    ),
    path(
        "notifications/",
        include(
            "safe_transaction_service.notifications.urls", namespace="notifications"
        ),
    ),
    path(
        "",
        include(
            "safe_transaction_service.safe_messages.urls", namespace="safe_messages"
        ),
    ),
    path(
        "tokens/", include("safe_transaction_service.tokens.urls", namespace="tokens")
    ),
]
urlpatterns_v2 = [
    path("", include("safe_transaction_service.history.urls_v2", namespace="history")),
]

if settings.ENABLE_ANALYTICS:
    urlpatterns_v2 += [
        path(
            "analytics/",
            include(
                "safe_transaction_service.analytics.urls_v2", namespace="analytics"
            ),
        ),
    ]

urlpatterns = swagger_urlpatterns + [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include((urlpatterns_v1, "v1"))),
    path("api/v2/", include((urlpatterns_v2, "v2"))),
    path("check/", lambda request: HttpResponse("Ok"), name="check"),
]


if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
        ] + urlpatterns

admin.autodiscover()
