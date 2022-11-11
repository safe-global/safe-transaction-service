from rest_framework.pagination import LimitOffsetPagination


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100
