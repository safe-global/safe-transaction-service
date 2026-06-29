# SPDX-License-Identifier: FSL-1.1-MIT
from .base import *  # noqa
from .base import env
from .base import (
    REDIS_URL,
    REDIS_CONNECTION_TIMEOUT_SECONDS,
    REDIS_TIMEOUT_SECONDS,
    REDIS_POOL_MAX_CONNECTIONS,
)


# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = True
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="aHdCBMHXuxIxEhfRGFRp7Cp3N9CqEZEEAvwZVlBCazKExkEnzvVs4bYWC8Qqh9lg",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": REDIS_CONNECTION_TIMEOUT_SECONDS,
            "SOCKET_TIMEOUT": REDIS_TIMEOUT_SECONDS,
            "CONNECTION_POOL_KWARGS": {"max_connections": REDIS_POOL_MAX_CONNECTIONS},
            # Mimicking memcache behavior.
            # http://niwinz.github.io/django-redis/latest/#_memcached_exceptions_behavior
            "IGNORE_EXCEPTIONS": True,
        },
    },
    "local_storage": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "local_mem",
    },
}

# Log redis exceptions ignored
DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS = True

# django-debug-toolbar
# ------------------------------------------------------------------------------
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#prerequisites
INSTALLED_APPS += ["debug_toolbar"]  # noqa F405

# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#middleware
MIDDLEWARE += [  # noqa F405
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "debug_toolbar_force.middleware.ForceDebugToolbarMiddleware",
]
# https://django-debug-toolbar.readthedocs.io/en/latest/configuration.html#debug-toolbar-config
DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}
# https://django-debug-toolbar.readthedocs.io/en/latest/installation.html#internal-ips
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]

# Enable to get the host from header
USE_X_FORWARDED_HOST = True

# SSO — Google OIDC + JWT verification
# ------------------------------------------------------------------------------
SSO_ENABLED = env.bool("SSO_ENABLED", default=False)
if SSO_ENABLED:
    USE_X_FORWARDED_PORT = True
    MIDDLEWARE.append(  # noqa F405
        "safe_transaction_service.utils.auth.GoogleOIDCMiddleware"
    )
    AUTHENTICATION_BACKENDS = [
        "safe_transaction_service.utils.auth.CustomRemoteUserBackend",
        # "django.contrib.auth.backends.ModelBackend",
    ]
    # When creating a user, give superuser permissions if email is in SSO_ADMINS
    # e.g. SSO_ADMINS=alice@safe.global,bob@safe.global
    SSO_ADMINS = env.list("SSO_ADMINS", default=[])
    # Google OAuth client ID — used to verify the JWT aud claim so only tokens
    # issued for this app are accepted. Must match the client_id in APISIX config.
    SSO_CLIENT_ID = env("SSO_CLIENT_ID")
    SSO_HOSTED_DOMAIN = env("SSO_HOSTED_DOMAIN", default="safe.global")
