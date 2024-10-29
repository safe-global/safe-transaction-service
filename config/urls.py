from django.conf import settings
from django.conf.urls import include
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.views import defaults as default_views

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from safe_transaction_service.utils.redis import cache_view_response

schema_cache_timeout = 60 * 60 * 24 * 7  # 1 week
swagger_urlpatterns = [
    path(
        "",
        cache_view_response(schema_cache_timeout, settings.SWAGGER_CACHE_KEY)(
            SpectacularSwaggerView.as_view(url_name="schema-json")
        ),
        name="schema-swagger-ui",
    ),
    path(
        r"schema/",
        cache_view_response(schema_cache_timeout, settings.SWAGGER_CACHE_KEY)(
            SpectacularAPIView().as_view()
        ),
        name="schema-json",
    ),
    path(
        "redoc/",
        cache_view_response(schema_cache_timeout, settings.SWAGGER_CACHE_KEY)(
            SpectacularRedocView.as_view(url_name="schema-redoc")
        ),
        name="schema-redoc",
    ),
]

urlpatterns_v1 = [
    path("", include("safe_transaction_service.history.urls", namespace="history")),
    path(
        "",
        include(
            "safe_transaction_service.account_abstraction.urls",
            namespace="account_abstraction",
        ),
    ),
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
