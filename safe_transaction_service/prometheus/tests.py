from django.test import TestCase

from .metrics import Metrics, get_metrics


class TestMetrics(TestCase):
    def test_metrics(self):
        metrics: Metrics = get_metrics()
        self.assertIsNotNone(metrics)
