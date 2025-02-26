from rest_framework import status
from rest_framework.exceptions import APIException


class InternalValidationError(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = "An internal validation error occurred."
    default_code = "internal_validation_error"
