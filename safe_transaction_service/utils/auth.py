# SPDX-License-Identifier: FSL-1.1-MIT
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.backends import RemoteUserBackend

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)


class GoogleOIDCMiddleware:
    """
    Authenticates requests by verifying a Google-issued RS256 JWT in the
    X-Enc-ID-Token header. Checks hosted domain (hd) and email_verified
    before creating a Django session via RemoteUserBackend.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.META.get("HTTP_X_ENC_ID_TOKEN", "")
        if token and request.user.is_authenticated:
            logger.debug(
                "SSO skipping JWT, session already active email=%s",
                request.user.username,
            )
        elif token and not request.user.is_authenticated:
            logger.info("SSO JWT verification started")
            claims = id_token.verify_oauth2_token(token, google_requests.Request())
            if claims.get("hd") != "safe.global":
                raise ValueError("JWT rejected: wrong hosted domain")
            if not claims.get("email_verified"):
                raise ValueError("JWT rejected: email not verified")
            user = authenticate(request, remote_user=claims["email"])
            if user and claims["email"] in settings.SSO_ADMINS:
                request.user = user
                login(request, user)
                logger.info("SSO authenticated email=%s", claims["email"])
            elif user:
                logger.warning(
                    "SSO access denied email=%s not in SSO_ADMINS", claims["email"]
                )
            else:
                logger.warning("SSO authentication failed email=%s", claims["email"])
        return self.get_response(request)


class CustomRemoteUserBackend(RemoteUserBackend):
    def authenticate(self, request, remote_user):
        if not remote_user:
            return None
        UserModel = get_user_model()
        username = self.clean_username(remote_user)
        user, created = UserModel._default_manager.get_or_create(
            **{UserModel.USERNAME_FIELD: username}
        )
        user = self.configure_user(request, user, created)
        return user if self.user_can_authenticate(user) else None

    def configure_user(self, request, user, created=True):
        user = super().configure_user(request, user, created)
        if created:
            logger.info("SSO user created email=%s", user.username)
        if user.username in settings.SSO_ADMINS:
            user.is_active = True
            user.is_superuser = True
            user.is_staff = True
            logger.info("SSO admin access granted email=%s", user.username)
        else:
            user.is_active = False
            logger.warning(
                "SSO access denied email=%s not in SSO_ADMINS", user.username
            )
        user.save()
        return user
