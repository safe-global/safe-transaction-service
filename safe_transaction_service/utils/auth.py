# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.backends import RemoteUserBackend
from django.http import HttpResponse

import google.auth.exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)


class GoogleOIDCMiddleware:
    """
    Runs on every request. Handles three cases:
    - No session: verifies the Google RS256 JWT in X-Enc-ID-Token, checks hosted
      domain (hd) and email_verified, then creates a Django session via
      CustomRemoteUserBackend if the email is in SSO_ADMINS. Returns 503 if
      Google's JWKS endpoint is unreachable.
    - Session exists + token present: re-checks SSO_ADMINS on every request and
      revokes the session immediately if the user has been removed.
    - Session exists + no token: logs the user out immediately (APISIX always
      forwards the token for valid sessions; absence means the request bypassed
      the proxy).
    """

    _google_request = google_requests.Request()

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.META.get("HTTP_X_ENC_ID_TOKEN", "")
        if token and not request.user.is_authenticated:
            # JWT present, no Django session — verify and create one.
            logger.info("SSO JWT verification started")
            try:
                claims = id_token.verify_oauth2_token(
                    token,
                    self._google_request,
                    audience=settings.SSO_CLIENT_ID,
                )
            except google.auth.exceptions.TransportError as exc:
                logger.error("SSO JWT verification failed: Google unreachable: %s", exc)
                return HttpResponse("SSO unavailable", status=503)
            if claims.get("hd") != settings.SSO_HOSTED_DOMAIN:
                raise ValueError("JWT rejected: wrong hosted domain")
            if not claims.get("email_verified"):
                raise ValueError("JWT rejected: email not verified")
            email = claims.get("email")
            if not email:
                raise ValueError("JWT rejected: missing email claim")
            user = authenticate(request, remote_user=email)
            if user:
                request.user = user
                login(request, user)
                logger.info("SSO authenticated email=%s", email)
            else:
                logger.warning("SSO access denied email=%s not in SSO_ADMINS", email)
        elif token and request.user.is_authenticated:
            # JWT present, Django session active — re-check SSO_ADMINS.
            if request.user.username not in settings.SSO_ADMINS:
                user = request.user
                user.is_active = False
                user.is_superuser = False
                user.is_staff = False
                user.save()
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
            # No JWT, Django session active — proxy bypass, force logout.
            user = request.user
            logout(request)
            logger.warning(
                "SSO session revoked email=%s: X-Enc-ID-Token header missing",
                user.username,
            )
        else:
            # No JWT, no Django session — request bypassed APISIX entirely.
            logger.warning("SSO no JWT, no session path=%s", request.path)
        return self.get_response(request)


class CustomRemoteUserBackend(RemoteUserBackend):
    def authenticate(self, request, remote_user):
        """
        Entry point called when no Django session exists. Finds or creates the user in
        the DB, then calls configure_user to set their permissions based on SSO_ADMINS.
        Always runs configure_user so SSO_ADMINS changes apply on the next login, not
        just on first login.
        """
        if not remote_user:
            logger.debug("SSO authenticate called with empty remote_user")
            return None
        UserModel = get_user_model()
        username = self.clean_username(remote_user)
        user, created = UserModel._default_manager.get_or_create(
            **{UserModel.USERNAME_FIELD: username}
        )
        user = self.configure_user(request, user, created)
        return user if self.user_can_authenticate(user) else None

    def configure_user(self, request, user, created=True):
        """
        Called by authenticate() on every login attempt. Sets is_active, is_superuser,
        and is_staff based on SSO_ADMINS membership. If the user is not in SSO_ADMINS,
        is_active is set to False and authenticate() returns None — no session is created.
        """
        user = super().configure_user(request, user, created)
        if created:
            logger.info("SSO first login, Django user created email=%s", user.username)
        if user.username in settings.SSO_ADMINS:
            user.is_active = True
            user.is_superuser = True
            user.is_staff = True
            logger.info("SSO admin access granted email=%s", user.username)
        else:
            user.is_active = False
            user.is_superuser = False
            user.is_staff = False
            logger.warning(
                "SSO access denied email=%s not in SSO_ADMINS", user.username
            )
        user.save()
        return user
