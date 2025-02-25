import json
import logging
import time
from dataclasses import asdict, dataclass


@dataclass()
class HttpRequestLog:
    url: str
    method: str
    startTime: int
    body: str | None = None


@dataclass
class HttpResponseLog:
    status: int
    endTime: int
    totalTime: int


@dataclass
class ErrorInfo:
    function: str
    line: int
    exceptionInfo: str | None = None


@dataclass
class TaskInfo:
    name: str
    id: str
    args: tuple
    kwargs: dict | None = None


@dataclass
class ContextMessageLog:
    session: str | None = None
    httpRequest: HttpRequestLog | None = None
    httpResponse: HttpResponseLog | None = None
    errorInfo: ErrorInfo | None = None
    taskInfo: TaskInfo | None = None


@dataclass
class JsonLog:
    level: str
    timestamp: int
    context: str
    message: str
    contextMessage: ContextMessageLog | None = None

    def to_json(self):
        return json.dumps(asdict(self))


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
            record.error_detail = ErrorInfo(
                function=record.funcName,
                line=record.lineno,
                exceptionInfo=str(record.exc_info),
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
        )

        json_log = JsonLog(
            level=record.levelname,
            timestamp=int(time.time() * 1000),
            context=f"{record.module}.{record.funcName}",
            message=record.getMessage(),
            contextMessage=context_message,
        )

        return json_log.to_json()
