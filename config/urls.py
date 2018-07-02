from django.conf import settings
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.views import defaults as default_views

from .swagger import get_swagger_view

schema_view = get_swagger_view(title='Gnosis SAFE API')


urlpatterns = [
    url(r'^$', schema_view),
    url(settings.ADMIN_URL, admin.site.urls),
    url(r'^api/v1/', include('safe_transaction_history.safe.urls', namespace='v1')),
    url(r'^check/', lambda request: HttpResponse("Ok"), name='check'),
]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        url(
            r"^400/$",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        url(
            r"^403/$",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        url(
            r"^404/$",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        url(r"^500/$", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [url(r"^__debug__/", include(debug_toolbar.urls))] + urlpatterns

admin.autodiscover()
