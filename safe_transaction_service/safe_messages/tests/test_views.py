import logging

from django.urls import reverse

from eth_account import Account
from rest_framework import status
from rest_framework.test import APITestCase

from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)

logger = logging.getLogger(__name__)


class TestViews(APITestCase):
    def test_safe_message_view(self):
        safe_message_id = 1
        response = self.client.get(
            reverse("v1:safe_messages:detail", args=(safe_message_id,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})

        safe_message = SafeMessageFactory()
        response = self.client.get(
            reverse("v1:safe_messages:detail", args=(safe_message.id,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "description": safe_message.description,
                "confirmations": [],
            },
        )

        # Add a confirmation
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        response = self.client.get(
            reverse("v1:safe_messages:detail", args=(safe_message.id,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "safe": safe_message.safe,
                "messageHash": safe_message.message_hash,
                "message": safe_message.message,
                "proposedBy": safe_message.proposed_by,
                "description": safe_message.description,
                "confirmations": [
                    {
                        "owner": safe_message_confirmation.owner,
                        "signature": safe_message_confirmation.signature,
                        "signatureType": "ETH_SIGN",
                    }
                ],
            },
        )

    def test_safe_messages_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:safe_messages:list", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )

        # Create a Safe message for a random Safe, it should not appear
        safe_message = SafeMessageFactory()
        response = self.client.get(
            reverse("v1:safe_messages:list", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )

        response = self.client.get(
            reverse("v1:safe_messages:list", args=(safe_message.safe,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "safe": safe_message.safe,
                        "messageHash": safe_message.message_hash,
                        "message": safe_message.message,
                        "proposedBy": safe_message.proposed_by,
                        "description": safe_message.description,
                        "confirmations": [],
                    }
                ],
            },
        )

        # Add a confirmation
        safe_message_confirmation = SafeMessageConfirmationFactory(
            safe_message=safe_message
        )
        response = self.client.get(
            reverse("v1:safe_messages:list", args=(safe_message.safe,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "safe": safe_message.safe,
                        "messageHash": safe_message.message_hash,
                        "message": safe_message.message,
                        "proposedBy": safe_message.proposed_by,
                        "description": safe_message.description,
                        "confirmations": [
                            {
                                "owner": safe_message_confirmation.owner,
                                "signature": safe_message_confirmation.signature,
                                "signatureType": "ETH_SIGN",
                            }
                        ],
                    }
                ],
            },
        )
