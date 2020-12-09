"""
Base settings to build other settings files upon.
"""

import environ
from corsheaders.defaults import default_headers as default_cors_headers

ROOT_DIR = environ.Path(__file__) - 3  # (safe_transaction_service/config/settings/base.py - 3 = safe-transaction-service/)
APPS_DIR = ROOT_DIR.path('safe_transaction_service')

env = environ.Env()

READ_DOT_ENV_FILE = env.bool('DJANGO_READ_DOT_ENV_FILE', default=False)
DOT_ENV_FILE = env('DJANGO_DOT_ENV_FILE', default=None)
if READ_DOT_ENV_FILE or DOT_ENV_FILE:
    DOT_ENV_FILE = DOT_ENV_FILE or '.env'
    # OS environment variables take precedence over variables from .env
    env.read_env(str(ROOT_DIR.path(DOT_ENV_FILE)))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool('DJANGO_DEBUG', False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = 'UTC'
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = 'en-us'
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-l10n
USE_L10N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DATABASES = {
    'default': env.db('DATABASE_URL'),
}
DATABASES['default']['ATOMIC_REQUESTS'] = False
DATABASES['default']['ENGINE'] = 'django_db_geventpool.backends.postgresql_psycopg2'
DATABASES['default']['OPTIONS'] = {
    'MAX_CONNS': 20,
    'REUSE_CONNS': 10
}

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = 'config.urls'
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = 'config.wsgi.application'

# APPS
# ------------------------------------------------------------------------------
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 'django.contrib.humanize', # Handy template tags

]
THIRD_PARTY_APPS = [
    'corsheaders',
    'rest_framework',
    'drf_yasg',
]
LOCAL_APPS = [
    'safe_transaction_service.contracts.apps.ContractsConfig',
    'safe_transaction_service.history.apps.HistoryConfig',
    'safe_transaction_service.notifications.apps.NotificationsConfig',
    'safe_transaction_service.tokens.apps.TokensConfig',
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = env('STATIC_ROOT', default=str(ROOT_DIR('staticfiles')))
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = '/static/'
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [
    str(APPS_DIR.path('static')),
]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR('media'))
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = '/media/'

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # https://docs.djangoproject.com/en/dev/ref/settings/#template-dirs
        'DIRS': [
            str(APPS_DIR.path('templates')),
        ],
        'OPTIONS': {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-debug
            'debug': DEBUG,
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-loaders
            # https://docs.djangoproject.com/en/dev/ref/templates/api/#loader-types
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# CORS
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_HEADERS = list(default_cors_headers) + ['if-match', 'if-modified-since', 'if-none-match']
CORS_EXPOSE_HEADERS = ['etag']

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (
    str(APPS_DIR.path('fixtures')),
)

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env('DJANGO_EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL regex.
ADMIN_URL = r'^admin/'
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [
    ("""Gnosis""", 'dev@gnosis.pm'),
]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS

# Celery
# ------------------------------------------------------------------------------
INSTALLED_APPS += [
    'safe_transaction_service.taskapp.celery.CeleryConfig',
    'django_celery_beat',
]
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='django://')
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-result_backend
if CELERY_BROKER_URL == 'django://':
    CELERY_RESULT_BACKEND = 'redis://'
else:
    CELERY_RESULT_BACKEND = CELERY_BROKER_URL
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ['json']
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = 'json'
# http://docs.celeryproject.org/en/latest/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = 'json'
# We are not interested in keeping results of tasks
CELERY_IGNORE_RESULT = True

# Django REST Framework
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    'PAGE_SIZE': 10,
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.AllowAny',),
    'DEFAULT_RENDERER_CLASSES': (
        'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
    ),
    'DEFAULT_PARSER_CLASSES': (
        'djangorestframework_camel_case.parser.CamelCaseJSONParser',
    ),
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.NamespaceVersioning',
}

# LOGGING
# ------------------------------------------------------------------------------
# See: https://docs.djangoproject.com/en/dev/ref/settings/#logging
# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins bon every HTTP 500 error when DEBUG=False.
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        },
        'ignore_succeeded_none': {
            '()': 'safe_transaction_service.taskapp.celery.IgnoreSucceededNone'
        },
    },
    'formatters': {
        'verbose': {
            'format': '%(asctime)s [%(levelname)s] [%(processName)s] %(message)s'
        },
        'celery_verbose': {
            'class': 'safe_transaction_service.taskapp.celery.PatchedCeleryFormatter',
            'format': '%(asctime)s [%(levelname)s] [%(task_id)s/%(task_name)s] %(message)s',
            # 'format': '%(asctime)s [%(levelname)s] [%(processName)s] [%(task_id)s/%(task_name)s] %(message)s'
        },

    },
    'handlers': {
        'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler'
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'celery_console': {
            'level': 'DEBUG',
            'filters': ['ignore_succeeded_none'],
            'class': 'logging.StreamHandler',
            'formatter': 'celery_verbose',
        },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'safe_transaction_service.history.indexers.internal_tx_indexer': {
            'level': 'INFO',
        },
        'safe_transaction_service.history.indexers.erc20_events_indexer': {
            'level': 'INFO',
        },
        'safe_transaction_service.history.indexers.tx_processor': {
            'level': 'INFO',
        },
        'safe_transaction_service.history.services.collectibles_service': {
            'level': 'INFO',
        },
        'celery': {
            'handlers': ['celery_console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,  # If not it will be out for the root logger too
        },
        'celery.worker.strategy': {  # All the "Received task..."
            'handlers': ['console'],
            'level': 'INFO' if DEBUG else 'WARNING',
            'propagate': False,  # If not it will be out for the root logger too
        },
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True
        },
        'django.security.DisallowedHost': {
            'level': 'ERROR',
            'handlers': ['console', 'mail_admins'],
            'propagate': True
        }
    }
}

REDIS_URL = env('REDIS_URL', default='redis://localhost:6379/0')

# Ethereum
# ------------------------------------------------------------------------------
ETHEREUM_NODE_URL = env('ETHEREUM_NODE_URL', default=None)
ETHEREUM_TRACING_NODE_URL = env('ETHEREUM_TRACING_NODE_URL', default=None)
ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT = env('ETH_INTERNAL_TXS_BLOCK_PROCESS_LIMIT', default=10000)
ETH_INTERNAL_NO_FILTER = env.bool('ETH_INTERNAL_NO_FILTER', default=False)

# Safe
# ------------------------------------------------------------------------------
# Number of blocks from the current block number needed to consider a transaction valid/stable
ETH_REORG_BLOCKS = env.int('ETH_REORG_BLOCKS', default=10)

# Oracles
ETH_UNISWAP_FACTORY_ADDRESS = env('ETH_UNISWAP_FACTORY_ADDRESS',
                                  default='0xc0a47dFe034B400B47bDaD5FecDa2621de6c4d95')
ETH_KYBER_NETWORK_PROXY_ADDRESS = env('ETH_KYBER_NETWORK_PROXY_ADDRESS',
                                      default='0x818E6FECD516Ecc3849DAf6845e3EC868087B755')

# Tokens
TOKENS_LOGO_BASE_URI = env('TOKENS_LOGO_BASE_URI', default='https://gnosis-safe-token-logos.s3.amazonaws.com/')
TOKENS_LOGO_EXTENSION = env('TOKENS_LOGO_EXTENSION', default='.png')

# Slack notifications
SLACK_API_WEBHOOK = env('SLACK_API_WEBHOOK', default=None)

# Notifications
NOTIFICATIONS_FIREBASE_CREDENTIALS_PATH = env('NOTIFICATIONS_FIREBASE_CREDENTIALS_PATH', default=None)
if NOTIFICATIONS_FIREBASE_CREDENTIALS_PATH:
    import json
    NOTIFICATIONS_FIREBASE_AUTH_CREDENTIALS = json.load(
        environ.Path(NOTIFICATIONS_FIREBASE_CREDENTIALS_PATH).file('firebase-credentials.json')
    )
