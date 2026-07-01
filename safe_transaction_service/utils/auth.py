# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login
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
    - No token, session active: passes through; session expires naturally per SESSION_COOKIE_AGE.
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
        elif token and authenticated:
            return self._reauthorize(request)
        elif not token and authenticated:
            logger.debug(
                "SSO no JWT on this route, Django session expires naturally",
                extra={"extra_data": {"email": request.user.username}},
            )
        else:
            logger.debug(
                "SSO anonymous request",
                extra={"extra_data": {"path": request.path}},
            )
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
            logger.error(
                "SSO JWT verification failed: Google unreachable",
                extra={"extra_data": {"error": str(exc)}},
            )
            return HttpResponse("SSO unavailable", status=503)
        except (google.auth.exceptions.GoogleAuthError, ValueError) as exc:
            logger.warning(
                "SSO JWT rejected", extra={"extra_data": {"error": str(exc)}}
            )
            return HttpResponse("Unauthorized", status=401)
        hd = (claims.get("hd") or "").lower()
        if not hd:
            logger.warning("SSO JWT rejected: missing hd claim")
            return HttpResponse("Unauthorized", status=401)
        if hd != settings.SSO_HOSTED_DOMAIN:
            logger.warning(
                "SSO JWT rejected: wrong hosted domain",
                extra={"extra_data": {"hd": hd}},
            )
            return HttpResponse("Unauthorized", status=401)
        email = (claims.get("email") or "").lower()
        if not email:
            logger.warning("SSO JWT rejected: missing email claim")
            return HttpResponse("Unauthorized", status=401)
        if not claims.get("email_verified"):
            logger.warning(
                "SSO JWT rejected: email not verified",
                extra={"extra_data": {"email": email}},
            )
            return HttpResponse("Unauthorized", status=401)
        logger.debug("SSO JWT verified", extra={"extra_data": {"email": email}})
        user = authenticate(request, remote_user=email)
        if not user:
            # Possible reasons: user is_active=False (intentional block) or backend misconfiguration.
            logger.warning(
                "SSO Django authenticate() returned None",
                extra={"extra_data": {"email": email}},
            )
            return HttpResponse("Unauthorized", status=401)

        login(request, user)
        logger.debug(
            "SSO Django session created",
            extra={
                "extra_data": {
                    "email": email,
                    "session_age_seconds": settings.SESSION_COOKIE_AGE,
                }
            },
        )
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
                "SSO_ADMINS membership changed, updating is_superuser",
                extra={
                    "extra_data": {
                        "email": user.username,
                        "old": user.is_superuser,
                        "new": is_sso_admin,
                    }
                },
            )
            CustomRemoteUserBackend.apply_user_flags(user, is_sso_admin=is_sso_admin)
        else:
            logger.debug(
                "SSO user.is_superuser in sync",
                extra={"extra_data": {"email": user.username}},
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
            logger.debug(
                "SSO Django user.is_active/is_staff set",
                extra={
                    "extra_data": {
                        "email": user.username,
                        "is_active": user.is_active,
                        "is_staff": user.is_staff,
                    }
                },
            )
        user.is_superuser = (
            is_sso_admin  # always authoritative — reflects SSO_ADMINS membership
        )
        logger.debug(
            "SSO Django user.is_superuser set",
            extra={
                "extra_data": {"email": user.username, "is_superuser": is_sso_admin}
            },
        )
        user.save()

    def configure_user(self, request, user, created=True):
        """
        Called by the parent's authenticate() on every login attempt. On first login,
        all verified org users get is_active=True and is_staff=True. On subsequent logins,
        is_active and is_staff are left untouched — set them to False in Django admin to
        block a non-admin user without removing them from Google Workspace. SSO_ADMINS
        members always get is_superuser=True; non-members always get is_superuser=False.

        NOTE: Adding a deactivated user's email to SSO_ADMINS will re-activate them on
        their next request (is_active=True is always enforced for admins). To permanently
        block a user, remove them from Google Workspace and from SSO_ADMINS.
        """
        if created:
            logger.info(
                "SSO first login, Django user created",
                extra={"extra_data": {"email": user.username}},
            )

        is_sso_admin = user.username in settings.SSO_ADMINS
        self.apply_user_flags(user, is_sso_admin, created=created)
        return user
