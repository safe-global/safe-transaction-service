from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

import django_filters.rest_framework
from rest_framework import filters
from rest_framework.generics import ListAPIView, RetrieveAPIView

from .filters import TokenFilter
from .models import Token
from .serializers import TokenSerializer


class TokenView(RetrieveAPIView):
    serializer_class = TokenSerializer
    lookup_field = 'address'
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 15))  # Cache 15 minutes
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TokensView(ListAPIView):
    serializer_class = TokenSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    filterset_class = TokenFilter
    search_fields = ('name', 'symbol')
    ordering_fields = '__all__'
    ordering = ('name',)
    queryset = Token.objects.all()

    @method_decorator(cache_page(60 * 15))  # Cache 15 minutes
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
