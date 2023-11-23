import logging
from typing import Type

from django.db.models import Model
from django.db.models.signals import post_save
from django.dispatch import receiver

from safe_transaction_service.history.services import (
    BalanceServiceProvider,
    CollectiblesServiceProvider,
)

from .models import Token

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Token, dispatch_uid="tokens.clear_cache")
def clear_cache(sender: Type[Model], instance: Token, created: bool, **kwargs) -> None:
    """
    Clear local Token caches when a token is manually updated

    :param sender:
    :param instance:
    :param created:
    :param kwargs:
    :return:
    """

    if not created:
        balance_service = BalanceServiceProvider()
        balance_service.cache_token_info.clear()

        collectibles_service = CollectiblesServiceProvider()
        collectibles_service.cache_token_info.clear()
