import datetime
import logging

from django.urls import reverse
from eth_account import Account
from hexbytes import HexBytes
from rest_framework import status
from rest_framework.test import APITestCase
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_contract
from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe import Safe, SafeOperation
from gnosis.safe.signatures import signatures_to_bytes
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import MultisigConfirmation, MultisigTransaction
from ..serializers import SafeMultisigTransactionHistorySerializer
from .factories import (MultisigTransactionConfirmationFactory,
                        MultisigTransactionFactory)

logger = logging.getLogger(__name__)


class TestHistoryViews(SafeTestCaseMixin, APITestCase):
    pass
