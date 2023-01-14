from django.contrib.admin import site
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from safe_transaction_service.tokens.admin import TokenAdmin
from safe_transaction_service.tokens.tests.factories import TokenFactory

from ..models import Token


class TestTokenAdmin(TestCase):
    request_factory = RequestFactory()

    @classmethod
    def setUpTestData(cls) -> None:
        cls.superuser = User.objects.create_superuser(
            "alfred", "alfred@example.com", "password"
        )
        cls.token1 = TokenFactory.create(logo=None)
        cls.token2 = TokenFactory.create()
        cls.token3 = TokenFactory.create()
        cls.tokens = {cls.token1, cls.token2, cls.token3}

    def setUp(self) -> None:
        self.token_admin = TokenAdmin(Token, site)
        return super().setUp()

    def test_unfiltered_lookup(self) -> None:
        request = self.request_factory.get("/")
        request.user = self.superuser

        changelist = self.token_admin.get_changelist_instance(request)

        # Queryset should contain all the tokens (no filter specified)
        self.assertEqual(set(changelist.get_queryset(request)), self.tokens)

    def test_has_logo_filter_lookup(self) -> None:
        request = self.request_factory.get("/", {"has_logo": "YES"})
        request.user = self.superuser

        changelist = self.token_admin.get_changelist_instance(request)

        # Queryset should contain tokens with logo (token2 and token3)
        self.assertEqual(
            set(changelist.get_queryset(request)), {self.token2, self.token3}
        )

    def test_has_no_logo_filter_lookup(self) -> None:
        request = self.request_factory.get("/", {"has_logo": "NO"})
        request.user = self.superuser

        changelist = self.token_admin.get_changelist_instance(request)

        # Queryset should contain tokens with no logo (token1)
        self.assertEqual(set(changelist.get_queryset(request)), {self.token1})
