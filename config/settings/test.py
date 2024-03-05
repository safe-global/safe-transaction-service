"""
With these settings, tests run faster.
"""

from .base import *  # noqa
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = False
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="q8lVkJGsIiHcTSQKaWIBsMVPOGnCnF6f7NDGup8KdDNmviSaZVhP0Nq3q3MolmFU",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    },
}

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# CELERY
CELERY_ALWAYS_EAGER = True

# Ganache #2 private key
ETHEREUM_TEST_PRIVATE_KEY = (
    "6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c"
)
ETH_REORG_BLOCKS = 1

# Fix error with `task_id` when running celery in eager mode
LOGGING["formatters"]["celery_verbose"] = LOGGING["formatters"]["verbose"]  # noqa F405
LOGGING["loggers"] = {  # noqa F405
    "safe_transaction_service": {
        "level": "DEBUG",
    }
}
