from django.contrib.admin.apps import AdminConfig


class OTPAdminConfig(AdminConfig):
    default_site = "django_otp.admin.OTPAdminSite"
