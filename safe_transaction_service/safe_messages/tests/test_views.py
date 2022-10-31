import logging

from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

logger = logging.getLogger(__name__)


class TestSafeMessageView(APITestCase):
    def test_safe_message_view(self):
        safe_message_id = "1"  # Invalid format
        response = self.client.get(
            reverse("v1:safe_messages:detail", args=(safe_message_id,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})
