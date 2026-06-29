# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.backends import RemoteUserBackend
from django.http import HttpResponse

import google.auth.exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)


class GoogleOIDCMiddleware:
    """
    Runs on every request. Handles four cases:
    - Token present, no session: verifies the Google RS256 JWT in X-Enc-ID-Token,
      checks hosted domain (hd) and email_verified, then creates a Django session
      via CustomRemoteUserBackend if the email is in SSO_ADMINS. Returns 503 if
      Google's JWKS endpoint is unreachable.
    - Token present, session active: skips JWT re-verification (APISIX already
      validated it) and re-checks SSO_ADMINS to enforce immediate revocation.
    - No token, session active: force logout. Either an authenticated user hitting
      a route not covered by OIDC, or an APISIX bypass (unlikely but a security concern).
    - No token, no session: anonymous request, passed through unchanged.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.META.get("HTTP_X_ENC_ID_TOKEN", "")
        if token and not request.user.is_authenticated:
            # JWT present, no session — verify token against Google JWKS and create a
            # Django session if the user is authorized.
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
            hd = claims.get("hd")
            if not hd:
                logger.warning("SSO JWT rejected: missing hd claim")
                return HttpResponse("Unauthorized", status=401)
            if hd != settings.SSO_HOSTED_DOMAIN:
                logger.warning("SSO JWT rejected: wrong hosted domain %r", hd)
                return HttpResponse("Unauthorized", status=401)
            email = claims.get("email")
            if not email:
                logger.warning("SSO JWT rejected: missing email claim")
                return HttpResponse("Unauthorized", status=401)
            if not claims.get("email_verified"):
                logger.warning("SSO JWT rejected: email not verified for %s", email)
                return HttpResponse("Unauthorized", status=401)
            user = authenticate(request, remote_user=email)
            if user:
                login(request, user)
                logger.info("SSO authenticated email=%s", email)
            else:
                logger.warning("SSO access denied email=%s not in SSO_ADMINS", email)
        elif token and request.user.is_authenticated:
            # JWT present, Django session active — re-check SSO_ADMINS.
            # JWT signature is intentionally not re-verified here: the Django session is
            # the trust anchor for authenticated users. Re-verifying against Google JWKS
            # on every request would add latency with no security benefit — APISIX already
            # validates the token before forwarding it. SSO_ADMINS is re-checked on every
            # request to enforce revocation without waiting for JWT expiry.
            if request.user.username not in settings.SSO_ADMINS:
                user = request.user
                CustomRemoteUserBackend.apply_admin_flags(user, is_admin=False)
                logout(request)
                logger.warning(
                    "SSO session revoked email=%s removed from SSO_ADMINS",
                    user.username,
                )
            else:
                logger.debug(
                    "SSO skipping JWT, session already active email=%s",
                    request.user.username,
                )
        elif not token and request.user.is_authenticated:
            # No JWT but Django session active. Two possible causes:
            #  1. Authenticated user hitting a route not covered by OIDC (expected).
            #  2. APISIX bypass (unlikely but a security concern).
            # Force logout in both cases since all sessions must be OIDC-backed.
            user = request.user
            logout(request)
            logger.info(
                "SSO logged out email=%s: no X-Enc-ID-Token header on this route",
                user.username,
            )
        else:
            # No JWT and no Django session. Two possible causes:
            #  1. Anonymous user hitting a public route (expected).
            #  2. Request that bypassed APISIX entirely (no session means no access to protected resources).
            logger.debug(
                "SSO anonymous request (no JWT, no session) path=%s", request.path
            )
        return self.get_response(request)


class CustomRemoteUserBackend(RemoteUserBackend):
    @staticmethod
    def apply_admin_flags(user, is_admin: bool) -> None:
        user.is_active = is_admin
        user.is_superuser = is_admin
        user.is_staff = is_admin
        user.save()

    def configure_user(self, request, user, created=True):
        """
        Called by the parent's authenticate() on every login attempt. Sets is_active,
        is_superuser, and is_staff based on SSO_ADMINS membership. If the user is not
        in SSO_ADMINS, is_active is set to False. Django's authenticate() wrapper then
        calls user_can_authenticate(), which rejects inactive users and returns None —
        no session is created.
        """
        if created:
            logger.info("SSO first login, Django user created email=%s", user.username)

        is_admin = user.username in settings.SSO_ADMINS
        self.apply_admin_flags(user, is_admin)

        if is_admin:
            logger.info("SSO admin access granted email=%s", user.username)
        else:
            logger.warning(
                "SSO access denied email=%s not in SSO_ADMINS", user.username
            )
        return user
