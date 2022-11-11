import logging
from unittest import mock
from unittest.mock import MagicMock

from django.urls import reverse

from eth_account import Account
from eth_account.messages import defunct_hash_message
from rest_framework import status
from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APITestCase

from gnosis.eth.eip712 import eip712_encode_hash
from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin
from gnosis.safe import Safe

from safe_transaction_service.safe_messages.models import (
    SafeMessage,
    SafeMessageConfirmation,
)
from safe_transaction_service.safe_messages.tests.factories import (
    SafeMessageConfirmationFactory,
    SafeMessageFactory,
)

logger = logging.getLogger(__name__)


class TestViews(EthereumTestCaseMixin, APITestCase):
    def test_safe_message_view(self):
        safe_message_id = 1
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message_id,))
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Not found."})

        safe_message = SafeMessageFactory()
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.id,))
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
            reverse("v1:safe_messages:message", args=(safe_message.id,))
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

    def test_safe_message_not_camel_case_view(self):
        safe_message_confirmation = SafeMessageConfirmationFactory()
        safe_message = safe_message_confirmation.safe_message
        safe_message.message = {"test_not_camel": 2}
        safe_message.save(update_fields=["message"])

        # Response message should not be camelcased
        response = self.client.get(
            reverse("v1:safe_messages:message", args=(safe_message.id,))
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

    @mock.patch(
        "safe_transaction_service.safe_messages.serializers.get_safe_owners",
        return_value=[],
    )
    def test_safe_messages_create_eip191_view(self, get_owners_mock: MagicMock):
        account = Account.create()
        safe_address = Account.create().address
        message = "Text to sign message"
        description = "Testing EIP191 message signing"
        message_hash = defunct_hash_message(text=message)
        safe = Safe(safe_address, self.ethereum_client)
        safe_message_hash = safe.get_message_hash(message_hash)
        signature = account.signHash(safe_message_hash)["signature"].hex()

        data = {
            "message": message,
            "description": description,
            "signature": signature,
        }
        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"{account.address} is not an owner of the Safe",
                        code="invalid",
                    )
                ]
            },
        )

        get_owners_mock.return_value = [account.address]
        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeMessage.objects.count(), 1)
        self.assertEqual(SafeMessageConfirmation.objects.count(), 1)

        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"Message with hash {safe_message_hash.hex()} for safe {safe_address} already exists in DB",
                        code="invalid",
                    )
                ]
            },
        )

    @mock.patch(
        "safe_transaction_service.safe_messages.serializers.get_safe_owners",
        return_value=[],
    )
    def test_safe_messages_create_eip712_view(self, get_owners_mock: MagicMock):
        def get_eip712_payload():
            address = "0x8e12f01dae5fe7f1122dc42f2cb084f2f9e8aa03"
            types = {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Mailbox": [
                    {"name": "owner", "type": "address"},
                    {"name": "messages", "type": "Message[]"},
                ],
                "Message": [
                    {"name": "sender", "type": "address"},
                    {"name": "subject", "type": "string"},
                    {"name": "isSpam", "type": "bool"},
                    {"name": "body", "type": "string"},
                ],
            }

            msgs = [
                {
                    "sender": address,
                    "subject": "Hello World",
                    "body": "The sparrow flies at midnight.",
                    "isSpam": False,
                },
                {
                    "sender": address,
                    "subject": "You may have already Won! :dumb-emoji:",
                    "body": "Click here for sweepstakes!",
                    "isSpam": True,
                },
            ]

            mailbox = {"owner": address, "messages": msgs}

            payload = {
                "types": types,
                "primaryType": "Mailbox",
                "domain": {
                    "name": "MyDApp",
                    "version": "3.0",
                    "chainId": 41,
                    "verifyingContract": address,
                },
                "message": mailbox,
            }

            return payload

        account = Account.create()
        safe_address = Account.create().address
        message = get_eip712_payload()
        description = "Testing EIP712 message signing"
        message_hash = eip712_encode_hash(message)
        safe = Safe(safe_address, self.ethereum_client)
        safe_message_hash = safe.get_message_hash(message_hash)
        signature = account.signHash(safe_message_hash)["signature"].hex()

        data = {
            "message": {},
            "description": description,
            "signature": signature,
        }
        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "message": [
                    ErrorDetail(
                        string="Provided dictionary is not a valid EIP712 message {}",
                        code="invalid",
                    )
                ]
            },
        )

        data["message"] = message
        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"{account.address} is not an owner of the Safe",
                        code="invalid",
                    )
                ]
            },
        )

        get_owners_mock.return_value = [account.address]
        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeMessage.objects.count(), 1)
        self.assertEqual(SafeMessageConfirmation.objects.count(), 1)

        response = self.client.post(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"Message with hash {safe_message_hash.hex()} for safe {safe_address} already exists in DB",
                        code="invalid",
                    )
                ]
            },
        )

    @mock.patch(
        "safe_transaction_service.safe_messages.serializers.get_safe_owners",
        return_value=[],
    )
    def test_safe_message_add_signature_view(self, get_owners_mock: MagicMock):
        # Test not existing id
        data = {"signature": "0x12"}
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(1,)), format="json", data=data
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test invalid signature
        safe_message_confirmation = SafeMessageConfirmationFactory()
        safe_message = safe_message_confirmation.safe_message
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.id,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string="1 owner signature was expected, 0 received",
                        code="invalid",
                    )
                ]
            },
        )

        # Test same signature
        data["signature"] = safe_message_confirmation.signature
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.id,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"Signature for owner {safe_message_confirmation.owner} already exists",
                        code="invalid",
                    )
                ]
            },
        )

        # Test not existing owner
        owner_account = Account.create()
        data["signature"] = owner_account.signHash(safe_message.message_hash)[
            "signature"
        ].hex()
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.id,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "non_field_errors": [
                    ErrorDetail(
                        string=f"{owner_account.address} is not an owner of the Safe",
                        code="invalid",
                    )
                ]
            },
        )

        # Test valid owner
        get_owners_mock.return_value = [owner_account.address]
        response = self.client.post(
            reverse("v1:safe_messages:signatures", args=(safe_message.id,)),
            format="json",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafeMessage.objects.count(), 1)
        self.assertEqual(SafeMessageConfirmation.objects.count(), 2)
        self.assertTrue(
            SafeMessageConfirmation.objects.filter(
                safe_message__safe=safe_message.safe, owner=owner_account.address
            ).exists()
        )

    def test_safe_messages_list_view(self):
        safe_address = Account.create().address
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )

        # Create a Safe message for a random Safe, it should not appear
        safe_message = SafeMessageFactory()
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_address,))
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(), {"count": 0, "next": None, "previous": None, "results": []}
        )

        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_message.safe,))
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
            reverse("v1:safe_messages:safe-messages", args=(safe_message.safe,))
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

    def test_safe_messages_list_not_camel_case_view(self):
        safe_message_confirmation = SafeMessageConfirmationFactory()
        safe_message = safe_message_confirmation.safe_message
        safe_message.message = {"test_not_camel": 2}
        safe_message.save(update_fields=["message"])

        # Response message should not be camelcased
        response = self.client.get(
            reverse("v1:safe_messages:safe-messages", args=(safe_message.safe,))
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
