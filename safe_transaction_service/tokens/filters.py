from django_filters import rest_framework as filters

from .models import Token


class TokenFilter(filters.FilterSet):
    class Meta:
        model = Token
        fields = {
            'name': ['exact'],
            'address': ['exact'],
            'symbol': ['exact'],
            'decimals': ['lt', 'gt', 'exact'],
        }
