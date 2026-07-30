# SPDX-License-Identifier: FSL-1.1-MIT
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

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
