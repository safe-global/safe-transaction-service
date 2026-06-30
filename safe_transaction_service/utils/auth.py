# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.backends import RemoteUserBackend
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

import google.auth.exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)


class GoogleOIDCMiddleware:
    """
    Runs on every request. Handles four cases:
    - Token present, no session: verifies the Google RS256 JWT in X-Enc-ID-Token,
      checks hosted domain (hd) and email_verified, then creates a Django session.
      New org users get is_active=True and is_staff=True; returning users keep their
      existing flags. SSO_ADMINS members always get is_superuser=True. Returns 503
      if Google's JWKS endpoint is unreachable.
    - Token present, session active: skips JWT re-verification (APISIX already
      validated it) and syncs is_superuser from SSO_ADMINS on every request.
    - No token, session active: force logout. Either an authenticated user hitting
      a route not covered by OIDC, or an APISIX bypass (unlikely but a security concern).
    - No token, no session: anonymous request, passed through unchanged.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        if not settings.SSO_CLIENT_ID:
            raise ImproperlyConfigured(
                "SSO_CLIENT_ID must be set when SSO_ENABLED=True"
            )
        if not settings.SSO_HOSTED_DOMAIN:
            raise ImproperlyConfigured(
                "SSO_HOSTED_DOMAIN must be set when SSO_ENABLED=True"
            )

    def __call__(self, request):
        token = request.META.get("HTTP_X_ENC_ID_TOKEN", "")
        authenticated = request.user.is_authenticated
        if token and not authenticated:
            return self._login(request, token)
        if token and authenticated:
            return self._reauthorize(request)
        if not token and authenticated:
            return self._force_logout(request)
        logger.debug("SSO anonymous request (no JWT, no session) path=%s", request.path)
        return self.get_response(request)

    def _login(self, request, token):
        """Verifies the Google RS256 JWT, validates hd and email_verified claims, then creates a Django session."""
        logger.debug("SSO JWT verification started")
        try:
            claims = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                audience=settings.SSO_CLIENT_ID,
            )
        except google.auth.exceptions.TransportError as exc:
            logger.error("SSO JWT verification failed: Google unreachable: %s", exc)
            return HttpResponse("SSO unavailable", status=503)
        except (google.auth.exceptions.GoogleAuthError, ValueError) as exc:
            logger.warning("SSO JWT rejected: %s", exc)
            return HttpResponse("Unauthorized", status=401)
        hd = (claims.get("hd") or "").lower()
        if not hd:
            logger.warning("SSO JWT rejected: missing hd claim")
            return HttpResponse("Unauthorized", status=401)
        if hd != settings.SSO_HOSTED_DOMAIN:
            logger.warning("SSO JWT rejected: wrong hosted domain hd=%s", hd)
            return HttpResponse("Unauthorized", status=401)
        email = (claims.get("email") or "").lower()
        if not email:
            logger.warning("SSO JWT rejected: missing email claim")
            return HttpResponse("Unauthorized", status=401)
        if not claims.get("email_verified"):
            logger.warning("SSO JWT rejected: email not verified email=%s", email)
            return HttpResponse("Unauthorized", status=401)
        user = authenticate(request, remote_user=email)
        if not user:
            # Possible reasons: user is_active=False (intentional block) or backend misconfiguration.
            logger.warning("SSO authenticate() returned None email=%s", email)
            return HttpResponse("Unauthorized", status=401)

        login(request, user)
        logger.info("SSO authenticated email=%s", email)
        return self.get_response(request)

    def _reauthorize(self, request):
        """
        JWT signature intentionally not re-verified; Django session is trust anchor.
        SSO_ADMINS membership synced on every request: adding/removing an email takes
        effect on the very next request without requiring a new login.
        """
        user = request.user
        is_sso_admin = user.username in settings.SSO_ADMINS
        if user.is_superuser != is_sso_admin:
            logger.info(
                "SSO updating is_superuser email=%s old=%s new=%s",
                user.username,
                user.is_superuser,
                is_sso_admin,
            )
            CustomRemoteUserBackend.apply_user_flags(user, is_sso_admin=is_sso_admin)
        else:
            logger.debug("SSO session still active email=%s", user.username)
        return self.get_response(request)

    def _force_logout(self, request):
        """
        No JWT but Django session active. Two possible causes:
        1. Authenticated user hitting a route not covered by OIDC (expected).
        2. APISIX bypass (unlikely but a security concern).
        Force logout in both cases since all sessions must be OIDC-backed.
        """
        user = request.user
        logout(request)
        logger.info(
            "SSO logged out email=%s: no X-Enc-ID-Token header on this route",
            user.username,
        )
        return self.get_response(request)


class CustomRemoteUserBackend(RemoteUserBackend):
    @staticmethod
    def apply_user_flags(user, is_sso_admin: bool, created: bool = False) -> None:
        # Admins always overridden
        # Non-admins only set on creation, Django controls after.
        if is_sso_admin or created:
            user.is_active = True
            user.is_staff = True
        user.is_superuser = (
            is_sso_admin  # always authoritative — reflects SSO_ADMINS membership
        )
        user.save()

    def configure_user(self, request, user, created=True):
        """
        Called by the parent's authenticate() on every login attempt. On first login,
        all verified org users get is_active=True and is_staff=True. On subsequent logins,
        is_active and is_staff are left untouched — set them to False in Django admin to
        block a user without removing them from Google Workspace. SSO_ADMINS members
        always get is_superuser=True; non-members always get is_superuser=False.
        """
        if created:
            logger.info("SSO first login, Django user created email=%s", user.username)

        is_sso_admin = user.username in settings.SSO_ADMINS
        self.apply_user_flags(user, is_sso_admin, created=created)

        logger.info(
            "SSO permissions set email=%s is_superuser=%s", user.username, is_sso_admin
        )
        return user
