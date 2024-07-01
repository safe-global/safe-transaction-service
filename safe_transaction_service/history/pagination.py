from typing import Optional

from django.http import HttpRequest

from rest_framework.pagination import LimitOffsetPagination


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100


class SmallPagination(LimitOffsetPagination):
    max_limit = 100
    default_limit = 20


class ListPagination(LimitOffsetPagination):

    def __init__(
        self,
        request: HttpRequest,
        max_limit: Optional[int] = None,
        default_limit: Optional[int] = None,
    ):
        super().__init__()
        self.request = request
        self.limit = self.get_limit(request)
        self.offset = self.get_offset(request)
        self.count: int = 0
        self.max_limit = max_limit if max_limit else self.max_limit
        self.default_limit = default_limit if default_limit else self.default_limit

    def set_count(self, value):
        self.count = value


class DummyPagination(LimitOffsetPagination):
    """
    Class to easily get limit and offset from a request, not intended to be used
    as a pagination class
    """

    def __init__(self, request: HttpRequest):
        super().__init__()
        self.request = request
        self.limit = self.get_limit(request)
        self.offset = self.get_offset(request)
        self.count: int = 0

    def set_count(self, value):
        self.count = value
