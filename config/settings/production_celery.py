from .production import *  # noqa

# Patch all the code to use Celery logger (if not just logs inside tasks.py are displayed with the
# task_id and task_name). This way every log will have the context information
for _, logger in LOGGING['loggers'].items():  # noqa F405
    key = 'handlers'
    if key in logger:
        logger[key] = ['celery_console']
