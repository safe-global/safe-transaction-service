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
SECRET_KEY = env("DJANGO_SECRET_KEY", default="q8lVkJGsIiHcTSQKaWIBsMVPOGnCnF6f7NDGup8KdDNmviSaZVhP0Nq3q3MolmFU")
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# CACHES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#caches
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": ""
    }
}

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-host
EMAIL_HOST = "localhost"
# https://docs.djangoproject.com/en/dev/ref/settings/#email-port
EMAIL_PORT = 1025

# CELERY
CELERY_ALWAYS_EAGER = True

SAFE_CONTRACT_ADDRESS = '0x2727D69C0BD14B1dDd28371B8D97e808aDc1C2f7'

# Ganache #2 private key
ETHEREUM_TEST_PRIVATE_KEY = '6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c'
SAFE_REORG_BLOCKS = 1
