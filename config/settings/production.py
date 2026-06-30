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

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL regex.
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

# Gunicorn
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["gunicorn"]  # noqa F405
