import datetime
import socket
from itertools import islice
from typing import Any, Iterable, Union

import gevent.socket


class FixedSizeDict(dict):
    """
    Fixed size dictionary to be used as an LRU cache

    Dictionaries are guaranteed to be insertion sorted from Python 3.7 onwards
    """

    def __init__(self, *args, maxlen=0, **kwargs):
        self._maxlen = maxlen
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)
        if self._maxlen > 0:
            if len(self) > self._maxlen:
                self.pop(next(iter(self)))


def chunks(elements: list[Any], n: int) -> Iterable[Any]:
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
    return socket.socket is gevent.socket.socket


def parse_boolean_query_param(value: Union[bool, str, int]) -> bool:
    return value in (True, "True", "true", "1", 1)


def datetime_to_str(value: datetime.datetime) -> str:
    """
    :param value: `datetime.datetime` value
    :return: ``ISO 8601`` date with ``Z`` format
    """
    value = value.isoformat()
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    return value
