from rest_framework import serializers

from .models import Token


class TokenSerializer(serializers.ModelSerializer):
    logo_uri = serializers.SerializerMethodField()

    class Meta:
        model = Token
        fields = '__all__'

    def get_logo_uri(self, obj: Token):
        return obj.get_full_logo_uri()
