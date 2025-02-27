import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def _get_exception_trace(exception: Exception) -> str:
    if str(exception):
        exception_trace = "{}: {}".format(exception.__class__.__name__, exception)
    else:
        exception_trace = exception.__class__.__name__
    return exception_trace


def _generate_response_data(exception_trace: str, message: str) -> dict:
    return {
        "exception": message,
        "trace": exception_trace,
    }


def _log_message(context: dict, exception_trace: str, exception: Exception):
    logger.warning(
        "%s - Exception: %s - Data received %s",
        context["request"].build_absolute_uri(),
        exception_trace,
        context["request"].data,
        exc_info=exception,
    )


def custom_exception_handler(exc, context):
    if isinstance(exc, NodeConnectionException):
        response = Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        exception_trace = _get_exception_trace(exc)
        response.data = _generate_response_data(
            exception_trace, "Problem connecting to Ethereum network"
        )
        _log_message(context, exception_trace, exc)

    elif isinstance(exc, CannotGetSafeInfoFromBlockchain):
        response = Response(status=status.HTTP_404_NOT_FOUND)
        exception_trace = _get_exception_trace(exc)
        response.data = _generate_response_data(
            exception_trace, "Safe info could not be retrieved from blockchain"
        )
        _log_message(context, exception_trace, exc)

    else:
        # Call REST framework's default exception handler,
        # to get the standard error response.
        response = exception_handler(exc, context)

    return response


class NodeConnectionException(IOError):
    pass


class InternalValidationError(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = "An internal validation error occurred."
    default_code = "internal_validation_error"


class SafeServiceException(Exception):
    pass


class CannotGetSafeInfoFromBlockchain(SafeServiceException):
    pass


class CannotGetSafeInfoFromDB(SafeServiceException):
    pass
