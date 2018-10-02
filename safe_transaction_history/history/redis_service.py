from django.conf import settings
from redis import Redis


class RedisService:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        self.redis = Redis.from_url(settings.REDIS_URL)
