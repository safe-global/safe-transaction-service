from typing import Any, List, Union

from django.core.signals import request_finished
from django.db import connection

from gevent.monkey import saved


def chunks(elements: List[Any], n: int):
    """
    :param elements: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(elements), n):
        yield elements[i : i + n]


def running_on_gevent() -> bool:
    return "sys" in saved


def close_gevent_db_connection():
    """
    Clean gevent db connections. Check `atomic block` to prevent breaking the tests (Django `TestCase` wraps tests
    inside an atomic block that rollbacks at the end of the test)
    https://github.com/jneight/django-db-geventpool#using-orm-when-not-serving-requests
    :return:
    """
    if not connection.in_atomic_block:
        request_finished.send(sender="greenlet")


def parse_boolean_query_param(value: Union[bool, str]) -> bool:
    if value in (True, "True", "true", "1"):
        return True
    else:
        return False
