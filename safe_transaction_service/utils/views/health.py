# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.db import connections
from django.http import HttpRequest, HttpResponse, JsonResponse

from safe_transaction_service.utils.redis import get_redis

logger = logging.getLogger(__name__)


def live(request: HttpRequest) -> HttpResponse:
    """
    Liveness probe. Answers as long as the process can serve requests, so no
    dependency is touched and no I/O is done.

    :param request:
    :return: ``200`` response
    """
    return HttpResponse("OK", content_type="text/plain")


def _is_database_healthy() -> bool:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        logger.warning("Readiness check failed for the database", exc_info=True)
        return False


def _is_redis_healthy() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        logger.warning("Readiness check failed for Redis", exc_info=True)
        return False


def ready(request: HttpRequest) -> JsonResponse:
    """
    Readiness probe. Checks the dependencies needed to serve API requests:
    the database and Redis (services like ``BalanceService`` or
    ``TransactionService`` read from it on every request).

    Celery workers and indexing lag are not part of it, as the API keeps
    serving data while they are down.

    Every dependency is checked on its own, so a broken one is reported as
    ``false`` instead of raising.

    :param request:
    :return: ``{"ready": bool, "db": bool, "redis": bool}`` with status ``200``
        when every dependency is healthy, ``503`` otherwise
    """
    database_healthy = _is_database_healthy()
    redis_healthy = _is_redis_healthy()
    is_ready = database_healthy and redis_healthy
    return JsonResponse(
        {"ready": is_ready, "db": database_healthy, "redis": redis_healthy},
        status=200 if is_ready else 503,
    )
