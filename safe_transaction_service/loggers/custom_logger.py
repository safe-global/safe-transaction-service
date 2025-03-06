import json
import logging
import time
import traceback
from dataclasses import asdict, dataclass


@dataclass()
class HttpRequestLog:
    url: str
    urlReplaced: str
    method: str
    timestamp: int
    body: str | None = None


@dataclass
class HttpResponseLog:
    status: int
    endTime: int
    totalTime: int
    errorMessage: dict | str | None = None


@dataclass
class ErrorInfo:
    function: str
    line: int
    exceptionInfo: str | None = None


@dataclass
class TaskInfo:
    name: str
    id: str
    args: tuple | None = None
    kwargs: dict | None = None


@dataclass
class ContextMessageLog:
    session: str | None = None
    httpRequest: HttpRequestLog | None = None
    httpResponse: HttpResponseLog | None = None
    errorInfo: ErrorInfo | None = None
    taskInfo: TaskInfo | None = None
    extraData: dict | None = None


@dataclass
class JsonLog:
    level: str
    timestamp: int
    context: str
    message: str
    lineno: int
    contextMessage: ContextMessageLog | None = None

    def _remove_null_values_from_log(self, json_log: dict):
        """
        Delete keys with the value ``None`` in a dictionary, recursively.
        """
        for key, value in list(json_log.items()):
            if value is None:
                del json_log[key]
            elif isinstance(value, dict):
                self._remove_null_values_from_log(value)
        return json_log

    def to_json(self):
        return json.dumps(self._remove_null_values_from_log(asdict(self)))


class SafeJsonFormatter(logging.Formatter):
    """
    Json formatter with following schema
    {
        level: str,
        timestamp: Datetime,
        context: str,
        message: str,
        contextMessage: <contextMessage>
    }
    """

    def format(self, record):
        if record.levelname == "ERROR":
            exception_info: str | None = None
            if record.exc_info:
                exc_type, exc_value, exc_tb = record.exc_info
                exception_info = "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                )

            record.error_detail = ErrorInfo(
                function=record.funcName,
                line=record.lineno,
                exceptionInfo=exception_info,
            )

        context_message = ContextMessageLog(
            session=record.session if hasattr(record, "session") else None,
            httpRequest=(
                record.http_request if hasattr(record, "http_request") else None
            ),
            httpResponse=(
                record.http_response if hasattr(record, "http_response") else None
            ),
            errorInfo=(
                record.error_detail if hasattr(record, "error_detail") else None
            ),
            taskInfo=record.task_detail if hasattr(record, "task_detail") else None,
            extraData=record.extra_data if hasattr(record, "extra_data") else None,
        )

        json_log = JsonLog(
            level=record.levelname,
            timestamp=int(time.time() * 1000),
            context=f"{record.module}.{record.funcName}",
            message=record.getMessage(),
            contextMessage=context_message,
            lineno=record.lineno,
        )

        return json_log.to_json()


def http_request_log(
    request, timestamp: int | None = None, log_data: bool = False
) -> HttpRequestLog:
    """
    Generate httpRequestLog from the providen request
    """
    route = request.resolver_match.route if request.resolver_match else request.path
    return HttpRequestLog(
        url=str(route),
        urlReplaced=request.path,
        method=request.method,
        timestamp=timestamp or int(time.time() * 1000),
        body=request.data if log_data else None,
    )
