# SPDX-License-Identifier: FSL-1.1-MIT
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, override_settings

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

    @override_settings(SSO_ADMINS=["dev@safe.global"])
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

        mock_verify.assert_called_once()
        mock_authenticate.assert_called_once_with(
            request, remote_user="dev@safe.global"
        )
        mock_login.assert_called_once_with(request, user)
        self.assertEqual(request.user, user)

    @override_settings(SSO_ADMINS=["other@safe.global"])
    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.login")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_user_not_in_admins_does_not_login(
        self, mock_authenticate, mock_login, mock_verify
    ):
        mock_verify.return_value = VALID_CLAIMS
        mock_authenticate.return_value = MagicMock()

        request = _anon_request(self.factory, token="valid.jwt.token")
        self.middleware(request)

        mock_login.assert_not_called()
        self.assertIsInstance(request.user, AnonymousUser)

    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_wrong_hosted_domain_raises(self, mock_authenticate, mock_verify):
        mock_verify.return_value = {
            **VALID_CLAIMS,
            "hd": "gmail.com",
            "email": "evil@gmail.com",
        }

        request = _anon_request(self.factory, token="bad.jwt.token")
        with self.assertRaises(ValueError):
            self.middleware(request)

        mock_authenticate.assert_not_called()

    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_unverified_email_raises(self, mock_authenticate, mock_verify):
        mock_verify.return_value = {**VALID_CLAIMS, "email_verified": False}

        request = _anon_request(self.factory, token="bad.jwt.token")
        with self.assertRaises(ValueError):
            self.middleware(request)

    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_invalid_jwt_raises(self, mock_authenticate, mock_verify):
        mock_verify.side_effect = ValueError("bad signature")

        request = _anon_request(self.factory, token="garbage")
        with self.assertRaises(ValueError):
            self.middleware(request)

        mock_authenticate.assert_not_called()

    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_no_token_passes_through(self, mock_authenticate, mock_verify):
        request = _anon_request(self.factory, token="")
        self.middleware(request)

        mock_verify.assert_not_called()
        mock_authenticate.assert_not_called()

    @patch("safe_transaction_service.utils.auth.id_token.verify_oauth2_token")
    @patch("safe_transaction_service.utils.auth.authenticate")
    def test_already_authenticated_skips_decode(self, mock_authenticate, mock_verify):
        request = _authed_request(self.factory)
        request.META["HTTP_X_ENC_ID_TOKEN"] = "valid.jwt.token"
        self.middleware(request)

        mock_verify.assert_not_called()
        mock_authenticate.assert_not_called()

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


class CustomRemoteUserBackendTest(SimpleTestCase):
    def setUp(self):
        self.backend = CustomRemoteUserBackend()
        self.request = RequestFactory().get("/admin/")

    def _make_user(self, username="dev@safe.global"):
        user = MagicMock()
        user.username = username
        return user

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("django.contrib.auth.backends.RemoteUserBackend.configure_user")
    def test_user_in_admins_list_gets_staff_superuser(self, mock_super):
        user = self._make_user("dev@safe.global")
        mock_super.return_value = user

        result = self.backend.configure_user(self.request, user, created=True)

        self.assertTrue(result.is_active)
        self.assertTrue(result.is_superuser)
        self.assertTrue(result.is_staff)
        result.save.assert_called()

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("safe_transaction_service.utils.auth.get_user_model")
    def test_authenticate_calls_configure_user_for_existing_user(
        self, mock_get_user_model
    ):
        user = self._make_user("dev@safe.global")
        user.is_active = True
        mock_model = MagicMock()
        mock_model.USERNAME_FIELD = "username"
        mock_model._default_manager.get_or_create.return_value = (user, False)
        mock_get_user_model.return_value = mock_model

        with patch.object(
            self.backend, "configure_user", return_value=user
        ) as mock_configure:
            self.backend.authenticate(self.request, "dev@safe.global")
            mock_configure.assert_called_once_with(self.request, user, False)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("django.contrib.auth.backends.RemoteUserBackend.configure_user")
    def test_deactivated_user_added_back_to_admins_is_reactivated(
        self, mock_super
    ):
        user = self._make_user("dev@safe.global")
        user.is_active = False
        mock_super.return_value = user

        self.backend.configure_user(self.request, user, created=False)

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("django.contrib.auth.backends.RemoteUserBackend.configure_user")
    def test_user_not_in_admins_list_deactivated(self, mock_super):
        user = self._make_user("other@safe.global")
        mock_super.return_value = user

        result = self.backend.configure_user(self.request, user, created=True)

        self.assertFalse(result.is_active)
        result.save.assert_called()

    @override_settings(SSO_ADMINS=[])
    @patch("django.contrib.auth.backends.RemoteUserBackend.configure_user")
    def test_empty_admins_list_deactivates_all(self, mock_super):
        user = self._make_user("dev@safe.global")
        mock_super.return_value = user

        result = self.backend.configure_user(self.request, user, created=True)

        self.assertFalse(result.is_active)

    @override_settings(SSO_ADMINS=["dev@safe.global"])
    @patch("django.contrib.auth.backends.RemoteUserBackend.configure_user")
    def test_returning_user_created_false_does_not_log_creation(self, mock_super):
        user = self._make_user("dev@safe.global")
        mock_super.return_value = user

        with self.assertLogs(
            "safe_transaction_service.utils.auth", level="INFO"
        ) as logs:
            self.backend.configure_user(self.request, user, created=False)

        self.assertFalse(any("user created" in msg for msg in logs.output))
