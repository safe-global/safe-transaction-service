import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    if isinstance(exc, NodeConnectionException):
        response = Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if str(exc):
            exception_str = "{}: {}".format(exc.__class__.__name__, exc)
        else:
            exception_str = exc.__class__.__name__
        response.data = {
            "exception": "Problem connecting to Ethereum network",
            "trace": exception_str,
        }

        logger.warning(
            "%s - Exception: %s - Data received %s",
            context["request"].build_absolute_uri(),
            exception_str,
            context["request"].data,
            exc_info=exc,
        )
    else:
        # Call REST framework's default exception handler,
        # to get the standard error response.
        response = exception_handler(exc, context)

    return response


class NodeConnectionException(IOError):
    pass
