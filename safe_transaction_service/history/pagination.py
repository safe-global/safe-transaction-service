from rest_framework.pagination import LimitOffsetPagination


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100


class SmallPagination(LimitOffsetPagination):
    max_limit = 100
    default_limit = 20


class ListPagination(LimitOffsetPagination):
    max_limit = 10

    def __init__(self, request, limit, offset):
        super().__init__()
        if limit < self.max_limit:
            self.limit = limit
        else:
            self.limit = self.max_limit
        self.offset = offset
        self.request = request
        self.count = 0

    def set_count(self, value):
        self.count = value
