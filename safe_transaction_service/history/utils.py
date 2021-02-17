import logging
import time
from typing import Any, Dict, List, Optional, Union

from django.conf import settings
from django.core.signals import request_finished
from django.db import connection
from django.http import HttpRequest

from gunicorn import glogging
from redis import Redis


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return not ('GET /check/' in message and '200' in message)


class CustomGunicornLogger(glogging.Logger):
    def setup(self, cfg):
        super().setup(cfg)

        # Add filters to Gunicorn logger
        logger = logging.getLogger("gunicorn.access")
        logger.addFilter(IgnoreCheckUrl())


class LoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger('LoggingMiddleware')

    def get_milliseconds_now(self):
        return int(time.time() * 1000)

    def __call__(self, request: HttpRequest):
        milliseconds = self.get_milliseconds_now()
        response = self.get_response(request)
        if request.resolver_match:
            route = request.resolver_match.route[1:] if request.resolver_match else request.path
            self.logger.info('MT::%s::%s::%s::%d::%s', request.method, route, self.get_milliseconds_now() - milliseconds,
                             response.status_code, request.path)
        return response


def close_gevent_db_connection():
    """
    Clean gevent db connections. Check `atomic block` to prevent breaking the tests (Django `TestCase` wraps tests
    inside an atomic block that rollbacks at the end of the test)
    https://github.com/jneight/django-db-geventpool#using-orm-when-not-serving-requests
    :return:
    """
    if not connection.in_atomic_block:
        request_finished.send(sender="greenlet")


def chunks(elements: List[Any], n: int):
    """
    :param elements: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(elements), n):
        yield elements[i:i + n]


def clean_receipt_log(receipt_logs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Clean receipt logs and make them JSON compliant
    :param receipt_logs:
    :return:
    """
    parsed_logs = {'data': receipt_logs['data'],
                   'topics': [topic.hex() for topic in receipt_logs['topics']]}
    return parsed_logs


def get_redis() -> Redis:
    if not hasattr(get_redis, 'redis'):
        get_redis.redis = Redis.from_url(settings.REDIS_URL)
    return get_redis.redis


def parse_boolean_query_param(value: Union[bool, str]) -> bool:
    if value in (True, 'True', 'true', '1'):
        return True
    else:
        return False
