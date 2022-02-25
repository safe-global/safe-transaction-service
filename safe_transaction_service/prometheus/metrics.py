from functools import cache

from django.db.models import Count

from prometheus_client import Counter, Gauge, Histogram

from safe_transaction_service.history.models import MultisigTransaction


@cache
def get_metrics() -> "Metrics":
    return Metrics()


class Metrics:
    DEFAULT_LATENCY_BUCKETS = (
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        25.0,
        50.0,
        75.0,
        float("inf"),
    )

    multisig_transaction_gauge = Gauge(
        "safe_multisig_transactions",
        "Multisig Transactions Processed by the Service",
        ["origin"],
    )
    http_requests_total = Counter(
        "django_http_requests_total",
        "Count of requests",
        ["method", "route", "path", "status"],
    )
    http_request_duration_seconds = Histogram(
        "django_http_request_duration_seconds",
        "Histogram of request processing time",
        ["method", "route", "path"],
        buckets=DEFAULT_LATENCY_BUCKETS,
    )

    def __init__(self):
        for m in (
            MultisigTransaction.objects.trusted()
            .values("origin")
            .annotate(total=Count("origin"))
        ):
            self.multisig_transaction_gauge.labels(origin=m["origin"]).set(m["total"])
