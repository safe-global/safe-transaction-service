from functools import wraps
from itertools import islice
from typing import Any, Iterable, List, Union

from django.core.signals import request_finished
from django.db import connection

from gevent.monkey import saved


def chunks(elements: List[Any], n: int) -> Iterable[Any]:
    """
    :param elements: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(elements), n):
        yield elements[i : i + n]


def chunks_iterable(iterable: Iterable[Any], n: int) -> Iterable[Iterable[Any]]:
    """
    Same as `chunks`, but for iterables

    :param iterable:
    :param n:
    :return:
    """
    it = iter(iterable)
    while True:
        chunk = tuple(islice(it, n))
        if not chunk:
            return None
        yield chunk


def running_on_gevent() -> bool:
    return "sys" in saved


def close_gevent_db_connection() -> None:
    """
    Clean gevent db connections. Check `atomic block` to prevent breaking the tests (Django `TestCase` wraps tests
    inside an atomic block that rollbacks at the end of the test)
    https://github.com/jneight/django-db-geventpool#using-orm-when-not-serving-requests
    """
    if not connection.in_atomic_block:
        request_finished.send(sender="greenlet")


def close_gevent_db_connection_decorator(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        finally:
            close_gevent_db_connection()

    return wrapper


def parse_boolean_query_param(value: Union[bool, str, int]) -> bool:
    return value in (True, "True", "true", "1", 1)
