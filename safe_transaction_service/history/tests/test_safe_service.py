from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.ethereum_client import TracingManager
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import InternalTxType, SafeMasterCopy
from ..services.safe_service import (
    CannotGetSafeInfoFromBlockchain,
    CannotGetSafeInfoFromDB,
    SafeCreationInfo,
    SafeInfo,
    SafeServiceProvider,
)
from ..services.safe_service import logger as safe_service_logger
from ..utils import clean_receipt_log
from .factories import (
    EthereumTxFactory,
    InternalTxFactory,
    SafeLastStatusFactory,
    SafeMasterCopyFactory,
)
from .mocks.mocks_safe_creation import (
    gelato_relay_creation_mock,
    multiple_safes_same_tx_creation_mock,
    multisend_creation_mock,
)
from .mocks.traces import create_trace, creation_internal_txs


class TestSafeService(SafeTestCaseMixin, TestCase):
    def setUp(self) -> None:
        self.safe_service = SafeServiceProvider()

    def test_get_safe_creation_info(self):
        """
        get_safe_creation_info should only return the TX of type CREATE
        """
        random_address = Account.create().address
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(
            contract_address=random_address,
            tx_type=InternalTxType.CREATE.value,
            ethereum_tx__status=0,
        )

        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(
            contract_address=random_address,
            ethereum_tx__status=1,
            tx_type=InternalTxType.CREATE.value,
        )

        InternalTxFactory(
            contract_address=random_address,
            ethereum_tx__status=1,
            tx_type=InternalTxType.CALL.value,
        )

        safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
        self.assertIsInstance(safe_creation_info, SafeCreationInfo)

    def test_get_safe_creation_info_with_tracing(self):
        """
        Traces are not stored on DB, so they must be recovered from the node
        """
        random_address = Account.create().address
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(
            contract_address=random_address,
            tx_type=InternalTxType.CREATE.value,
            ethereum_tx__status=0,
        )
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        with mock.patch.object(
            TracingManager,
            "trace_transaction",
            autospec=True,
            return_value=[create_trace],
        ):
            InternalTxFactory(
                contract_address=random_address,
                ethereum_tx__status=1,
                tx_type=InternalTxType.CREATE.value,
                trace_address="0",
            )
            safe_creation_info = self.safe_service.get_safe_creation_info(
                random_address
            )
            self.assertIsInstance(safe_creation_info, SafeCreationInfo)

    def test_get_safe_creation_info_without_tracing_but_with_proxy_factory(self):
        """
        Tracing is not used, so traces must be fetched from DB if possible. L2 indexer "emulates" creation traces
        if ``ProxyCreation`` event is detected (ProxyFactory used)

        :return:
        """
        random_address = Account.create().address
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        creation_trace = InternalTxFactory(
            contract_address=random_address,
            tx_type=InternalTxType.CREATE.value,
            ethereum_tx__status=1,
            trace_address="0",
        )
        safe_creation = self.safe_service.get_safe_creation_info(random_address)
        self.assertEqual(safe_creation.creator, creation_trace.ethereum_tx._from)
        self.assertEqual(safe_creation.factory_address, creation_trace._from)
        self.assertIsNone(safe_creation.master_copy)
        self.assertIsNone(safe_creation.setup_data)

        setup_trace = InternalTxFactory(
            ethereum_tx=creation_trace.ethereum_tx,
            ethereum_tx__status=1,
            trace_address="0,0",
            data=b"1234",
        )
        safe_creation = self.safe_service.get_safe_creation_info(random_address)
        self.assertEqual(safe_creation.creator, creation_trace.ethereum_tx._from)
        self.assertEqual(safe_creation.factory_address, creation_trace._from)
        self.assertEqual(safe_creation.master_copy, setup_trace.to)
        self.assertEqual(bytes(safe_creation.setup_data), b"1234")

    def test_get_safe_creation_info_without_tracing_nor_proxy_factory(self):
        """
        Tracing is not used, so traces must be fetched from DB if possible. L2 indexer cannot "emulate" creation traces
        as ProxyFactory was not used

        :return:
        """

        random_address = Account.create().address
        creation_trace = InternalTxFactory(
            contract_address=random_address,
            ethereum_tx__status=1,
            tx_type=InternalTxType.CREATE.value,
            trace_address="0",
            ethereum_tx__data=None,
        )

        # Setup can be done by a transfer to a contract, no need to have data
        safe_creation = self.safe_service.get_safe_creation_info(random_address)
        self.assertEqual(safe_creation.creator, creation_trace.ethereum_tx._from)
        self.assertEqual(safe_creation.factory_address, creation_trace._from)
        self.assertIsNone(safe_creation.master_copy)
        self.assertIsNone(safe_creation.setup_data)

    @mock.patch.object(
        TracingManager, "trace_transaction", return_value=creation_internal_txs
    )
    def test_get_safe_creation_info_with_next_trace(
        self, trace_transaction_mock: MagicMock
    ):
        random_address = Account.create().address
        InternalTxFactory(
            contract_address=random_address,
            tx_type=InternalTxType.CREATE.value,
            ethereum_tx__status=1,
            trace_address="",
        )
        safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
        self.assertIsInstance(safe_creation_info, SafeCreationInfo)
        self.assertEqual(
            safe_creation_info.master_copy, "0x8942595A2dC5181Df0465AF0D7be08c8f23C93af"
        )
        self.assertTrue(safe_creation_info.setup_data)
        trace_transaction_mock.return_value = []
        safe_creation_info = self.safe_service.get_safe_creation_info(random_address)
        self.assertIsNone(safe_creation_info.master_copy)
        self.assertIsNone(safe_creation_info.setup_data)

    def test_get_safe_info_from_blockchain(self):
        SafeMasterCopy.objects.get_version_for_address.cache_clear()
        safe_address = Account.create().address
        with self.assertRaises(CannotGetSafeInfoFromBlockchain):
            self.safe_service.get_safe_info_from_blockchain(safe_address)

        safe = self.deploy_test_safe()
        safe_info = self.safe_service.get_safe_info_from_blockchain(safe.address)
        self.assertIsInstance(safe_info, SafeInfo)
        self.assertEqual(safe_info.address, safe.address)
        self.assertEqual(safe_info.owners, safe.retrieve_owners())
        self.assertEqual(safe_info.threshold, safe.retrieve_threshold())
        self.assertEqual(
            safe_info.fallback_handler, self.compatibility_fallback_handler.address
        )
        self.assertEqual(safe_info.guard, NULL_ADDRESS)
        self.assertEqual(safe_info.version, None)  # No SafeMasterCopy

        version = "4.8.15162342"
        SafeMasterCopyFactory(address=safe_info.master_copy, version=version)

        safe_info = self.safe_service.get_safe_info_from_blockchain(safe.address)
        self.assertEqual(safe_info.version, version)
        SafeMasterCopy.objects.get_version_for_address.cache_clear()

    def test_get_safe_info_from_db(self):
        safe_address = Account.create().address
        with self.assertRaises(CannotGetSafeInfoFromDB):
            self.safe_service.get_safe_info_from_db(safe_address)

        safe_last_status = SafeLastStatusFactory(address=safe_address, guard=None)
        self.assertIsNone(safe_last_status.guard)

        safe_info = self.safe_service.get_safe_info_from_db(safe_address)
        self.assertIsInstance(safe_info, SafeInfo)
        self.assertEqual(safe_info.guard, NULL_ADDRESS)
        self.assertEqual(safe_info.version, None)

    def test_decode_creation_data(self):
        for creation_mock in (multisend_creation_mock, gelato_relay_creation_mock):
            with self.subTest(creation_mock=creation_mock):
                proxy_creation_data_list = self.safe_service._decode_creation_data(
                    creation_mock["data"]
                )
                self.assertEqual(len(proxy_creation_data_list), 1)
                proxy_creation_data = proxy_creation_data_list[0]
                self.assertEqual(
                    proxy_creation_data.singleton, creation_mock["expected_singleton"]
                )
                self.assertEqual(
                    proxy_creation_data.initializer,
                    creation_mock["expected_initializer"],
                )
                self.assertEqual(
                    proxy_creation_data.salt_nonce, creation_mock["expected_salt_nonce"]
                )

    def test_decode_creation_data_multiple_safes_same_tx(self):
        ethereum_tx = EthereumTxFactory(
            logs=[
                clean_receipt_log(log)
                for log in multiple_safes_same_tx_creation_mock["tx_logs"]
            ]
        )
        self.assertEqual(
            ethereum_tx.get_deployed_proxies_from_logs(),
            multiple_safes_same_tx_creation_mock["proxies_deployed"],
        )

        # There are 2 Safe creations inside of this transaction
        results = self.safe_service._decode_creation_data(
            multiple_safes_same_tx_creation_mock["data"]
        )
        self.assertEqual(len(results), 2)

        # We need to get the right one for every Safe
        for safe_address in multiple_safes_same_tx_creation_mock["proxies_deployed"]:
            with self.subTest(safe_address=safe_address):
                proxy_creation_data = self.safe_service._process_creation_data(
                    safe_address,
                    multiple_safes_same_tx_creation_mock["data"],
                    ethereum_tx,
                )
                creation_mock = multiple_safes_same_tx_creation_mock[safe_address]
                self.assertEqual(
                    proxy_creation_data.singleton, creation_mock["expected_singleton"]
                )
                self.assertEqual(
                    proxy_creation_data.initializer,
                    creation_mock["expected_initializer"],
                )
                self.assertEqual(
                    proxy_creation_data.salt_nonce, creation_mock["expected_salt_nonce"]
                )

        with self.assertLogs(safe_service_logger, level="WARNING") as cm:
            random_safe_address = Account.create().address
            self.assertIsNone(
                self.safe_service._process_creation_data(
                    random_safe_address,
                    multiple_safes_same_tx_creation_mock["data"],
                    ethereum_tx,
                )
            )

            self.assertIn(
                f'[{random_safe_address}] Proxy creation data is not matching the proxies deployed {multiple_safes_same_tx_creation_mock["proxies_deployed"]}',
                cm.output[0],
            )
