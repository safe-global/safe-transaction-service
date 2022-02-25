from django.http import HttpResponse

import prometheus_client


def export_to_django_view(request):
    """
    Exports /metrics as a Django view.
    """
    registry = prometheus_client.REGISTRY
    metrics_page = prometheus_client.generate_latest(registry)
    return HttpResponse(
        metrics_page, content_type=prometheus_client.CONTENT_TYPE_LATEST
    )
