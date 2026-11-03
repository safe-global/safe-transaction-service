# SPDX-License-Identifier: FSL-1.1-MIT
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from rest_framework import status

from ..swagger import IgnoreVersionSchemaGenerator


class TestSafeAutoSchema(TestCase):
    def test_banned_safe_views_document_451(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.auth = None
        schema = IgnoreVersionSchemaGenerator().get_schema(request=request, public=True)
        paths = schema["paths"]

        def get_operation(path: str, method: str) -> dict:
            self.assertIn(path, paths)
            return paths[path][method]

        # Every view guarded by BannedSafeMixin documents the 451 response
        for path, method in (
            ("/api/v1/safes/{address}/", "get"),
            ("/api/v1/safes/{address}/balances/", "get"),
            ("/api/v1/safes/{address}/multisig-transactions/", "get"),
            ("/api/v1/safes/{address}/multisig-transactions/", "post"),
            ("/api/v1/safes/{address}/messages/", "post"),
            ("/api/v1/safes/{address}/safe-operations/", "get"),
            ("/api/v2/safes/{address}/collectibles/", "get"),
        ):
            with self.subTest(path=path, method=method):
                self.assertIn("451", get_operation(path, method)["responses"])

        # Views not guarded by the mixin don't
        for path, method in (
            ("/api/v1/owners/{address}/safes/", "get"),
            ("/api/v1/modules/{address}/safes/", "get"),
            ("/api/v1/about/", "get"),
        ):
            with self.subTest(path=path, method=method):
                self.assertNotIn("451", get_operation(path, method)["responses"])


class TestSchemaView(TestCase):
    def get_schema(self) -> dict:
        response = self.client.get(reverse("schema-json") + "?format=json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_schema_declares_optional_bearer_api_key(self):
        schema = self.get_schema()

        security_schemes = schema["components"]["securitySchemes"]
        self.assertEqual(set(security_schemes), {"bearerAuth"})
        self.assertEqual(security_schemes["bearerAuth"]["type"], "http")
        self.assertEqual(security_schemes["bearerAuth"]["scheme"], "bearer")
        self.assertEqual(schema["security"], [{"bearerAuth": []}, {}])
        operations_with_security = [
            f"{method} {path}"
            for path, path_item in schema["paths"].items()
            for method, operation in path_item.items()
            if "security" in operation
        ]
        self.assertEqual(operations_with_security, [])

    def test_schema_excludes_analytics(self):
        paths = self.get_schema()["paths"]

        self.assertNotIn(
            reverse("v2:analytics:analytics-multisig-txs-by-origin"), paths
        )
        self.assertFalse([path for path in paths if "analytics" in path])
        self.assertIn(reverse("v1:history:about"), paths)

    @override_settings(SCHEMA_SERVER_URL="https://api.example.com")
    def test_schema_servers_with_server_url(self):
        self.assertEqual(
            self.get_schema()["servers"], [{"url": "https://api.example.com"}]
        )

    @override_settings(SCHEMA_SERVER_URL=None)
    def test_schema_servers_without_server_url(self):
        self.assertNotIn("servers", self.get_schema())
