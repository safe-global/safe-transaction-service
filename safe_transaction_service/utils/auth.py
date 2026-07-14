# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.backends import RemoteUserBackend
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

import cachecontrol
import google.auth.exceptions
import requests as requests_lib
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)


class _Unauthorized(Exception):
    pass


# Caching recommended by google.oauth2.id_token — by default certs are re-fetched on every call.
# https://github.com/googleapis/google-auth-library-python/blob/main/google/oauth2/id_token.py#L46-L54
_google_request = google_requests.Request(
    session=cachecontrol.CacheControl(requests_lib.Session())
)


class GoogleOIDCMiddleware:
    """
    Runs on every request. Handles four cases:
    - Token present, no session: verifies the Google RS256 JWT forwarded in the
      configured SSO_ID_TOKEN_HEADER, checks hosted domain (hd) and email_verified,
      then creates a Django session.
      New org users get is_active=True and is_staff=True; returning users keep their
      existing flags. SSO_ADMINS members always get is_superuser=True. Returns 503
      if Google's JWKS endpoint is unreachable.
    - Token present, session active: re-verifies the Google JWT (JWKS certs cached
      in memory, no network latency after warmup) and syncs is_superuser from SSO_ADMINS.
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
        token = request.META.get(settings.SSO_ID_TOKEN_HEADER, "")
        authenticated = request.user.is_authenticated
        try:
            if token and not authenticated:
                return self._login(request, token)
            elif token and authenticated:
                return self._reauthorize(request, token)
        except google.auth.exceptions.TransportError as exc:
            logger.error(
                "SSO JWT verification failed: Google unreachable",
                extra={"extra_data": {"error": str(exc)}},
            )
            return HttpResponse("SSO unavailable", status=503)
        except (
            google.auth.exceptions.GoogleAuthError,
            ValueError,
            _Unauthorized,
        ) as exc:
            logger.warning(
                "SSO JWT rejected", extra={"extra_data": {"error": str(exc)}}
            )
            return HttpResponse("Unauthorized", status=401)
        if not token and authenticated:
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

    def _verify_token(self, token) -> dict:
        """Returns claims dict. Raises TransportError or GoogleAuthError on failure."""
        return id_token.verify_oauth2_token(
            token, _google_request, audience=settings.SSO_CLIENT_ID
        )

    def _login(self, request, token):
        """Verifies the Google RS256 JWT, validates hd and email_verified claims, then creates a Django session."""
        logger.debug("SSO JWT verification started")
        claims = self._verify_token(token)
        hd = (claims.get("hd") or "").lower()
        if not hd:
            raise _Unauthorized("missing hd claim")
        if hd != settings.SSO_HOSTED_DOMAIN:
            raise _Unauthorized(f"wrong hosted domain: {hd}")
        email = claims.get("email") or ""
        if not email:
            raise _Unauthorized("missing email claim")
        if not claims.get("email_verified"):
            raise _Unauthorized(f"email not verified: {email}")
        logger.debug("SSO JWT verified", extra={"extra_data": {"email": email}})
        user = authenticate(request, remote_user=email)
        if not user:
            raise _Unauthorized(f"authenticate() returned None for {email}")
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

    def _reauthorize(self, request, token):
        """
        Re-verifies the Google JWT on every admin request. JWKS certs are cached
        in memory for 6 hours (Google's Cache-Control TTL), so this is a local
        crypto operation after warmup — no network latency per request.
        SSO_ADMINS membership synced on every request.
        """
        self._verify_token(token)
        CustomRemoteUserBackend.apply_user_flags(request.user)
        return self.get_response(request)


class CustomRemoteUserBackend(RemoteUserBackend):
    def clean_username(self, username):
        return username.lower()

    @staticmethod
    def apply_user_flags(user, created: bool = False) -> None:
        is_sso_admin = user.username in settings.SSO_ADMINS
        # Admins always overridden
        # Non-admins only set on creation, Django controls after.
        if is_sso_admin or created:
            user.is_active = True
            user.is_staff = True
        user.is_superuser = (
            is_sso_admin  # always authoritative — reflects SSO_ADMINS membership
        )
        user.save(update_fields=["is_active", "is_staff", "is_superuser"])
        logger.debug(
            "SSO user flags saved",
            extra={
                "extra_data": {
                    "email": user.username,
                    "is_active": user.is_active,
                    "is_staff": user.is_staff,
                    "is_superuser": is_sso_admin,
                }
            },
        )

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

        self.apply_user_flags(user, created=created)
        return user
