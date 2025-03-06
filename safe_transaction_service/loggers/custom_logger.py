import json
import logging
import time
import traceback
from dataclasses import asdict, dataclass

from django.http import HttpRequest

from celery._state import get_current_task
from celery.app.log import TaskFormatter
from gunicorn import glogging


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
    errorMessage: str | None = None


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


def get_milliseconds_now():
    return int(time.time() * 1000)


def http_request_log(
    request, timestamp: int | None = None, log_data: bool = False
) -> HttpRequestLog:
    """
    Generate httpRequestLog from provided request
    """
    route = request.resolver_match.route if request.resolver_match else request.path
    return HttpRequestLog(
        url=str(route),
        urlReplaced=request.path,
        method=request.method,
        timestamp=timestamp or get_milliseconds_now(),
        body=request.data if log_data else None,
    )


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

    def format(self, record) -> str:
        """
        Format logging record as json string.
        """

        if record.levelname == "ERROR":
            exception_info: str | None = None
            # Check if the error contains exception data
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

        # Generate context_message
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
            timestamp=get_milliseconds_now(),
            context=f"{record.module}.{record.funcName}",
            message=record.getMessage(),
            contextMessage=context_message,
            lineno=record.lineno,
        )

        return json_log.to_json()


class PatchedCeleryFormatter(SafeJsonFormatter):  # pragma: no cover

    def format(self, record):
        task = get_current_task()
        if task and task.request:
            # For gevent pool, task_id will be something like `7ab44cb4-aacf-444e-bc20-4cbaa2a7b082`. For logs
            # is better to get it short
            task_id = task.request.id[:8] if task.request.id else task.request.id
            # Task name usually has all the package, better cut the first part for logging
            task_name = task.name.split(".")[-1] if task.name else task.name
            task_detail = TaskInfo(
                id=task_id,
                name=task_name,
                args=task.request.args,
                kwargs=task.request.kwargs,
            )
            record.__dict__.update(task_detail=task_detail)
        return super().format(record)


class LoggingMiddleware:
    """
    Http Middleware to generate request and response logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("LoggingMiddleware")

    def __call__(self, request: HttpRequest):
        start_time = get_milliseconds_now()
        response = self.get_response(request)
        if request.resolver_match:
            end_time = get_milliseconds_now()
            delta = end_time - start_time
            http_request = http_request_log(request, start_time)
            content: str | None = None
            if 400 <= response.status_code < 500:
                print(response.data)
                content = str(response.data)

            http_response = HttpResponseLog(
                response.status_code, end_time, delta, content
            )
            self.logger.info(
                "Http request",
                extra={
                    "http_response": http_response,
                    "http_request": http_request,
                },
            )
        return response


class CustomGunicornLogger(glogging.Logger):
    def setup(self, cfg):
        super().setup(cfg)

        # Add filters to Gunicorn logger
        logger = logging.getLogger("gunicorn.access")
        logger.addFilter(IgnoreCheckUrl())


class IgnoreSucceededNone(logging.Filter):
    """
    Ignore Celery messages like:
    ```
        Task safe_transaction_service.history.tasks.index_internal_txs_task[89ad3c46-aeb3-48a1-bd6f-2f3684323ca8]
        succeeded in 1.0970600529108196s: None
    ```
    They are usually emitted when a redis lock is active
    """

    def filter(self, rec: logging.LogRecord):
        message = rec.getMessage()
        return not ("Task" in message and "succeeded" in message and "None" in message)


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not ("GET /check/" in message and "200" in message)


class PatchedCeleryFormatterOriginal(TaskFormatter):  # pragma: no cover
    """
    Patched to work as an standard logging formatter. Basic version
    """

    def __init__(self, fmt=None, datefmt=None, style="%"):
        super().__init__(fmt=fmt, use_color=True)
