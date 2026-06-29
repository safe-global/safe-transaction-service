# SPDX-License-Identifier: FSL-1.1-MIT
from unittest.mock import ANY, MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

import google.auth.exceptions

from safe_transaction_service.utils.auth import (
    CustomRemoteUserBackend,
    GoogleOIDCMiddleware,
)

VALID_CLAIMS = {
    "email": "dev@safe.global",
    "hd": "safe.global",
    "email_verified": True,
    "sub": "1234567890",
}


def _anon_request(factory, path="/admin/", token=""):
    request = factory.get(path)
    request.META["HTTP_X_ENC_ID_TOKEN"] = token
    request.user = AnonymousUser()
    return request


def _authed_request(factory, path="/admin/", username="dev@safe.global"):
    request = factory.get(path)
    user = MagicMock()
    user.is_authenticated = True
    user.username = username
    request.user = user
    return request


class GoogleOIDCMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.get_response = MagicMock(return_value=MagicMock())
        self.middleware = GoogleOIDCMiddleware(self.get_response)

    @override_settings(
        SSO_ADMINS=["dev@safe.global"],
        SSO_HOSTED_DOMAIN="safe.global",
        SSO_CLIENT_ID="test-client-id.apps.googleusercontent.com",
    )
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.login")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_valid_token_authenticates_user(
        self, mock_authenticate, mock_login, mock_verify
    ):
        mock_verify.return_value = VALID_CLAIMS
        user = MagicMock()
        mock_authenticate.return_value = user

        request = _anon_request(self.factory, token="valid.jwt.token")
        self.middleware(request)

        mock_verify.assert_called_once_with(
            "valid.jwt.token",
            ANY,
            audience="test-client-id.apps.googleusercontent.com",
        )
        mock_authenticate.assert_called_once_with(
            request, remote_user="dev@safe.global"
        )
        mock_login.assert_called_once_with(request, user)
        self.get_response.assert_called_once_with(request)

    @override_settings(
        SSO_ADMINS=["dev@safe.global"],
        SSO_HOSTED_DOMAIN="safe.global",
        SSO_CLIENT_ID="my-client-id.apps.googleusercontent.com",
    )
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.login")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_sso_client_id_passed_as_audience(
        self, mock_authenticate, mock_login, mock_verify
    ):
        mock_verify.return_value = VALID_CLAIMS
        mock_authenticate.return_value = MagicMock()

        request = _anon_request(self.factory, token="valid.jwt.token")
        self.middleware(request)

        mock_verify.assert_called_once_with(
            "valid.jwt.token",
            ANY,
            audience="my-client-id.apps.googleusercontent.com",
        )
        self.get_response.assert_called_once_with(request)

    @override_settings(
        SSO_ADMINS=["other@safe.global"],
        SSO_HOSTED_DOMAIN="safe.global",
        SSO_CLIENT_ID=None,
    )
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.login")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_user_not_in_admins_does_not_login(
        self, mock_authenticate, mock_login, mock_verify
    ):
        mock_verify.return_value = VALID_CLAIMS
        mock_authenticate.return_value = (
            None  # backend returns None when not in SSO_ADMINS
        )

        request = _anon_request(self.factory, token="valid.jwt.token")
        self.middleware(request)

        mock_login.assert_not_called()
        self.assertIsInstance(request.user, AnonymousUser)
        self.get_response.assert_called_once_with(request)

    @override_settings(SSO_HOSTED_DOMAIN="safe.global", SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_wrong_hosted_domain_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.return_value = {
            **VALID_CLAIMS,
            "hd": "gmail.com",
            "email": "evil@gmail.com",
        }

        request = _anon_request(self.factory, token="bad.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_HOSTED_DOMAIN="safe.global", SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_missing_hd_claim_returns_401(self, mock_authenticate, mock_verify):
        claims_without_hd = {k: v for k, v in VALID_CLAIMS.items() if k != "hd"}
        mock_verify.return_value = claims_without_hd

        request = _anon_request(self.factory, token="bad.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_HOSTED_DOMAIN="safe.global", SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_unverified_email_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.return_value = {**VALID_CLAIMS, "email_verified": False}

        request = _anon_request(self.factory, token="bad.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_HOSTED_DOMAIN="safe.global", SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_missing_email_claim_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.return_value = {**VALID_CLAIMS, "email": None}

        request = _anon_request(self.factory, token="valid.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_HOSTED_DOMAIN="safe.global", SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_empty_hd_claim_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.return_value = {**VALID_CLAIMS, "hd": ""}

        request = _anon_request(self.factory, token="valid.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_expired_jwt_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.side_effect = ValueError("Token expired")

        request = _anon_request(self.factory, token="expired.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_invalid_jwt_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.side_effect = ValueError("bad signature")

        request = _anon_request(self.factory, token="garbage")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @override_settings(SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_google_auth_error_returns_401(self, mock_authenticate, mock_verify):
        mock_verify.side_effect = google.auth.exceptions.GoogleAuthError("wrong issuer")

        request = _anon_request(self.factory, token="bad.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 401)
        mock_authenticate.assert_not_called()

    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_no_token_passes_through(self, mock_authenticate, mock_verify):
        request = _anon_request(self.factory, token="")
        self.middleware(request)

        mock_verify.assert_not_called()
        mock_authenticate.assert_not_called()
        self.get_response.assert_called_once_with(request)

    def test_no_jwt_no_session_logs_debug(self):
        request = _anon_request(self.factory, token="")
        with self.assertLogs(
            "safe_transaction_service.utils.auth", level="DEBUG"
        ) as logs:
            self.middleware(request)

        self.assertTrue(any("anonymous request" in msg for msg in logs.output))
        self.get_response.assert_called_once_with(request)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_already_authenticated_skips_decode(self, mock_authenticate, mock_verify):
        request = _authed_request(self.factory)
        request.META["HTTP_X_ENC_ID_TOKEN"] = "valid.jwt.token"
        self.middleware(request)

        mock_verify.assert_not_called()
        mock_authenticate.assert_not_called()
        self.get_response.assert_called_once_with(request)

    @patch("safe_transaction_service.utils.auth.logout")
    def test_authenticated_user_without_token_is_logged_out(self, mock_logout):
        # No X-Enc-ID-Token header — APISIX not forwarding; session revoked immediately.
        request = _authed_request(self.factory)
        self.middleware(request)

        mock_logout.assert_called_once_with(request)
        self.get_response.assert_called_once_with(request)

    @override_settings(SSO_ADMINS=[])
    @patch("safe_transaction_service.utils.auth.logout")
    def test_authenticated_user_removed_from_admins_is_revoked(self, mock_logout):
        request = _authed_request(self.factory, username="dev@safe.global")
        request.META["HTTP_X_ENC_ID_TOKEN"] = "valid.jwt.token"
        user = request.user

        self.middleware(request)

        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        user.save.assert_called_once()
        mock_logout.assert_called_once_with(request)
        self.get_response.assert_called_once_with(request)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("safe_transaction_service.utils.auth.logout")
    def test_authenticated_user_in_admins_stays_logged_in(self, mock_logout):
        request = _authed_request(self.factory, username="dev@safe.global")
        request.META["HTTP_X_ENC_ID_TOKEN"] = "valid.jwt.token"

        self.middleware(request)

        mock_logout.assert_not_called()
        self.get_response.assert_called_once_with(request)

    @override_settings(SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    def test_google_transport_error_returns_503(self, mock_verify):
        mock_verify.side_effect = google.auth.exceptions.TransportError("network error")

        request = _anon_request(self.factory, token="valid.jwt.token")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 503)

    @override_settings(SSO_HOSTED_DOMAIN="safe.global", SSO_CLIENT_ID=None)
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_authenticate_returns_none_does_not_set_user(
        self, mock_authenticate, mock_verify
    ):
        mock_verify.return_value = VALID_CLAIMS
        mock_authenticate.return_value = None

        request = _anon_request(self.factory, token="valid.jwt.token")
        self.middleware(request)

        self.assertIsInstance(request.user, AnonymousUser)
        self.get_response.assert_called_once_with(request)


class CustomRemoteUserBackendTest(SimpleTestCase):
    def setUp(self):
        self.backend = CustomRemoteUserBackend()
        self.request = RequestFactory().get("/admin/")

    def _make_user(self, username="dev@safe.global"):
        user = MagicMock()
        user.username = username
        return user

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    def test_user_in_admins_list_gets_staff_superuser(self):
        user = self._make_user("dev@safe.global")

        result = self.backend.configure_user(self.request, user, created=True)

        self.assertTrue(result.is_active)
        self.assertTrue(result.is_superuser)
        self.assertTrue(result.is_staff)
        result.save.assert_called_once()

    def test_authenticate_empty_remote_user_returns_none(self):
        result = self.backend.authenticate(self.request, remote_user="")
        self.assertIsNone(result)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("django.contrib.auth.backends.UserModel")
    def test_authenticate_calls_configure_user_for_existing_user(self, mock_user_model):
        user = self._make_user("dev@safe.global")
        mock_user_model.USERNAME_FIELD = "username"
        mock_user_model._default_manager.get_or_create.return_value = (user, False)

        with patch.object(
            self.backend, "configure_user", return_value=user
        ) as mock_configure:
            self.backend.authenticate(self.request, "dev@safe.global")
            mock_configure.assert_called_once_with(self.request, user, created=False)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    def test_deactivated_user_added_back_to_admins_is_reactivated(self):
        user = self._make_user("dev@safe.global")
        user.is_active = False

        self.backend.configure_user(self.request, user, created=False)

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        user.save.assert_called_once()

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    def test_user_not_in_admins_list_deactivated(self):
        user = self._make_user("other@safe.global")

        result = self.backend.configure_user(self.request, user, created=True)

        self.assertFalse(result.is_active)
        self.assertFalse(result.is_superuser)
        self.assertFalse(result.is_staff)
        result.save.assert_called_once()

    @override_settings(SSO_ADMINS=[])
    def test_empty_admins_list_deactivates_all(self):
        user = self._make_user("dev@safe.global")

        result = self.backend.configure_user(self.request, user, created=True)

        self.assertFalse(result.is_active)
        self.assertFalse(result.is_superuser)
        self.assertFalse(result.is_staff)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    def test_returning_user_created_false_does_not_log_creation(self):
        user = self._make_user("dev@safe.global")

        with self.assertLogs(
            "safe_transaction_service.utils.auth", level="INFO"
        ) as logs:
            self.backend.configure_user(self.request, user, created=False)

        self.assertFalse(any("user created" in msg for msg in logs.output))
        self.assertTrue(any("admin access granted" in msg for msg in logs.output))

    def test_apply_admin_flags_grants_all_flags(self):
        user = self._make_user()
        CustomRemoteUserBackend.apply_admin_flags(user, is_admin=True)
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        user.save.assert_called_once()

    def test_apply_admin_flags_revokes_all_flags(self):
        user = self._make_user()
        CustomRemoteUserBackend.apply_admin_flags(user, is_admin=False)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)
        user.save.assert_called_once()
