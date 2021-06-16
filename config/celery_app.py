import os

import django.conf

from celery import Celery

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("safe_transaction_service")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
for k in dir(django.conf.settings):
    print(k, getattr(django.conf.settings, k))
print(django.conf.settings.CELERY_ALWAYS_EAGER)
app.config_from_object("django.conf:settings")
# app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
