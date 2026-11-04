# SPDX-License-Identifier: FSL-1.1-MIT
from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.test import RequestFactory, TestCase, override_settings
from django.urls import clear_script_prefix, reverse

from drf_spectacular.settings import patched_settings
from rest_framework import status

from ..swagger import IgnoreVersionSchemaGenerator

PREFIX = "/tx-service/sep"
LOCAL_STORAGE_LOCMEM = {
    "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
    "local_storage": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-schema-vary",
    },
}


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
    def get_schema(self, prefix: str = "") -> dict:
        headers = {"X-Forwarded-Prefix": prefix} if prefix else {}
        response = self.client.get(
            reverse("schema-json") + "?format=json", headers=headers
        )
        # ProxyPrefixMiddleware sets the script prefix of the thread, used by reverse()
        clear_script_prefix()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_schema_declares_optional_bearer_api_key(self):
        """
        `bearerAuth` is the only scheme, optional at the root, and no operation
        overrides it
        """
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

    def test_every_operation_allows_anonymous_access(self):
        """
        The hook documents the API key as optional everywhere, so a view that
        needs authentication must be excluded from the schema
        """
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.auth = None
        with patched_settings({"POSTPROCESSING_HOOKS": []}):
            schema = IgnoreVersionSchemaGenerator().get_schema(
                request=request, public=True
            )

        protected = [
            f"{method} {path}"
            for path, path_item in schema["paths"].items()
            for method, operation in path_item.items()
            if {} not in operation.get("security", [])
        ]
        self.assertEqual(protected, [])

    @override_settings(SCHEMA_SERVER_URL="https://api.example.com")
    def test_schema_conventional_aliases(self):
        """The aliases serve the same JSON schema as `schema/`, also behind the proxy"""
        for prefix in ("", PREFIX):
            schema = self.get_schema(prefix=prefix)
            headers = {"X-Forwarded-Prefix": prefix} if prefix else {}
            for url_name in ("schema-openapi-json", "schema-openapi-json-v1"):
                with self.subTest(url_name=url_name, prefix=prefix):
                    response = self.client.get(reverse(url_name), headers=headers)
                    clear_script_prefix()
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    self.assertEqual(
                        response["Content-Type"], "application/vnd.oai.openapi+json"
                    )
                    self.assertEqual(response.json(), schema)
                    if prefix:
                        self.assertTrue(
                            all(path.startswith(prefix) for path in schema["paths"])
                        )

    def test_schema_excludes_analytics(self):
        """The admin-only analytics endpoint is not in the public schema"""
        paths = self.get_schema()["paths"]

        self.assertNotIn(
            reverse("v2:analytics:analytics-multisig-txs-by-origin"), paths
        )
        self.assertFalse([path for path in paths if "analytics" in path])
        self.assertIn(reverse("v1:history:about"), paths)

    @override_settings(SCHEMA_SERVER_URL="https://api.example.com/")
    def test_schema_servers_match_prefixed_paths(self):
        """
        Behind the proxy, the server URL (without a trailing `/`) plus each path
        gives the public URL
        """
        schema = self.get_schema(prefix=PREFIX)

        self.assertEqual(schema["servers"], [{"url": "https://api.example.com"}])
        self.assertTrue(all(path.startswith(PREFIX) for path in schema["paths"]))
        about = PREFIX + reverse("v1:history:about")
        self.assertIn(about, schema["paths"])
        self.assertEqual(
            schema["servers"][0]["url"] + about,
            "https://api.example.com/tx-service/sep/api/v1/about/",
        )

    @override_settings(SCHEMA_SERVER_URL="https://api.example.com")
    def test_schema_without_prefix_has_no_servers(self):
        """A request without the proxy prefix gets relative paths and no `servers`"""
        schema = self.get_schema()

        self.assertNotIn("servers", schema)
        self.assertIn(reverse("v1:history:about"), schema["paths"])

    @override_settings(SCHEMA_SERVER_URL=None)
    def test_schema_servers_without_server_url(self):
        """Without `SCHEMA_SERVER_URL` there is no `servers`, also behind the proxy"""
        self.assertNotIn("servers", self.get_schema(prefix=PREFIX))

    @override_settings(
        SCHEMA_SERVER_URL="https://api.example.com", CACHES=LOCAL_STORAGE_LOCMEM
    )
    def test_schema_cache_is_per_prefix(self):
        """A cached schema fetched without the prefix is not served behind the proxy"""
        caches["local_storage"].clear()
        self.assertNotIn("servers", self.get_schema())

        schema = self.get_schema(prefix=PREFIX)

        self.assertEqual(schema["servers"], [{"url": "https://api.example.com"}])
        self.assertTrue(all(path.startswith(PREFIX) for path in schema["paths"]))

    @override_settings(
        SCHEMA_SERVER_URL="https://api.example.com", CACHES=LOCAL_STORAGE_LOCMEM
    )
    def test_schema_cache_varies_on_prefix_value(self):
        """
        A prefix that is a string prefix of the request path (`/sch`) gets its own
        cache entry, so it cannot decide the schema of unprefixed fetches
        """
        caches["local_storage"].clear()
        self.assertIn("servers", self.get_schema(prefix="/sch"))

        schema = self.get_schema()

        self.assertNotIn("servers", schema)
        self.assertIn(reverse("v1:history:about"), schema["paths"])
