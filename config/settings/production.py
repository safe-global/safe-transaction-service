from .base import *  # noqa
from .base import env

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

REDIS_URL = env.str("REDIS_URL")

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # Mimicing memcache behavior.
            # http://niwinz.github.io/django-redis/latest/#_memcached_exceptions_behavior
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
)
# https://docs.djangoproject.com/en/3.2/ref/settings/#csrf-trusted-origins
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# SSO (tested with https://github.com/buzzfeed/sso)
# ------------------------------------------------------------------------------
# Be really careful when enabling SSO. If the `SSO_USERNAME_HEADER` can be spoofed
# auth is broken and anyone will be able to log in as any user
SSO_ENABLED = env.bool("SSO_ENABLED", default=False)
if SSO_ENABLED:
    SSO_USERNAME_HEADER = env.str(
        "SSO_USERNAME_HEADER", default="HTTP_X_FORWARDED_USER"
    )
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True
    MIDDLEWARE.append(  # noqa F405
        "safe_transaction_service.utils.auth.CustomHeaderRemoteUserMiddleware"
    )
    AUTHENTICATION_BACKENDS = [
        "safe_transaction_service.utils.auth.CustomRemoteUserBackend"
        # "django.contrib.auth.backends.ModelBackend",
    ]
    # When creating a user, give superuser permissions if username is in SSO_ADMIN
    SSO_ADMINS = env.list("SSO_ADMINS", default=["richard", "uxio"])

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL regex.
ADMIN_URL = env("DJANGO_ADMIN_URL", default="admin/")

# Gunicorn
# ------------------------------------------------------------------------------
INSTALLED_APPS += ["gunicorn"]  # noqa F405
