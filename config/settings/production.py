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
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY")
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# DATABASES
# ------------------------------------------------------------------------------
# DATABASES['default'] = env.db('DATABASE_URL')  # noqa F405
DATABASES["default"]["ATOMIC_REQUESTS"] = False  # noqa F405

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

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
)
# https://docs.djangoproject.com/en/5.0/ref/settings/#csrf-trusted-origins
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# SSO — Google OIDC + JWT verification
# ------------------------------------------------------------------------------
# Replaces the legacy SSO_USERNAME_HEADER / CustomHeaderRemoteUserMiddleware approach.
# SSO_USERNAME_HEADER is no longer read — remove it from your environment.
#
# The reverse proxy (APISIX) handles the Google OIDC flow and must be configured to
# forward the raw RS256-signed ID token as the X-Enc-ID-Token request header.
# GoogleOIDCMiddleware verifies the JWT signature against Google's public JWKS
# before trusting anything in the header — the token is never accepted on trust alone.
#
# Required env vars when SSO_ENABLED=true:
#   SSO_ADMINS       — comma-separated list of emails granted Django admin access
#   SSO_CLIENT_ID    — Google OAuth client ID (must match APISIX config); used to
#                      verify the JWT aud claim so tokens from other apps are rejected
# Optional:
#   SSO_HOSTED_DOMAIN — Google Workspace domain to enforce (default: safe.global)
SSO_ENABLED = env.bool("SSO_ENABLED", default=False)
if SSO_ENABLED:
    USE_X_FORWARDED_HOST = True
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
    SSO_CLIENT_ID = env("SSO_CLIENT_ID", default=None)
    SSO_HOSTED_DOMAIN = env("SSO_HOSTED_DOMAIN", default="safe.global")

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL regex.
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

# Gunicorn
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["gunicorn"]  # noqa F405
