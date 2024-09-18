from django.conf import settings
from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.middleware import RemoteUserMiddleware


class CustomHeaderRemoteUserMiddleware(RemoteUserMiddleware):
    """
    Headers that buzfeed SSO sends
    X-Forwarded-Email: tanjiro.kamado@safe.global
    X-Forwarded-For: 81.211.153.216, 81.13.44.29
    X-Forwarded-Groups: developers@safe.global
    X-Forwarded-Host: safe-transaction.dev.gnosisdev.com
    X-Forwarded-Host: safe-transaction.dev.gnosisdev.com
    X-Forwarded-Port: 443
    X-Forwarded-Proto: https
    X-Forwarded-Scheme: https
    X-Forwarded-User: tanjiro.kamado
    """

    header = settings.SSO_USERNAME_HEADER


class CustomRemoteUserBackend(RemoteUserBackend):
    def configure_user(self, request, user):
        """
        Configure a user after creation and return the updated user.

        By default, return the user unmodified.
        """
        user = super().configure_user(request, user)
        if user.username in settings.SSO_ADMINS:
            user.is_superuser = True
            user.is_staff = True
            user.save()
        return user
