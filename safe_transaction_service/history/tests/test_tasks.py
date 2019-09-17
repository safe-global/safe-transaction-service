import logging

from django.test import TestCase

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_contract
from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe import Safe, SafeOperation
from gnosis.safe.signatures import signatures_to_bytes
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import MultisigConfirmation, MultisigTransaction
from .factories import (MultisigConfirmationFactory,
                        MultisigTransactionFactory)

logger = logging.getLogger(__name__)


class TestTasks(SafeTestCaseMixin, TestCase):
    pass
