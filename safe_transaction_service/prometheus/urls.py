from django.urls import path

from .views import export_to_django_view

app_name = "prometheus"

urlpatterns = [
    path("", export_to_django_view, name="prometheus-metrics"),
]
