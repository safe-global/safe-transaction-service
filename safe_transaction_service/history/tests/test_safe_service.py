from unittest import mock
from unittest.mock import MagicMock

from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes
from safe_eth.eth.constants import NULL_ADDRESS
from safe_eth.eth.ethereum_client import TracingManager
from safe_eth.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import SafeMasterCopy
from ..services.safe_service import (
    CannotGetSafeInfoFromBlockchain,
    CannotGetSafeInfoFromDB,
    SafeCreationInfo,
    SafeInfo,
    SafeServiceProvider,
)
from .factories import InternalTxFactory, SafeLastStatusFactory, SafeMasterCopyFactory
from .mocks.traces import create_trace, creation_internal_txs


class TestSafeService(SafeTestCaseMixin, TestCase):
    def setUp(self) -> None:
        self.safe_service = SafeServiceProvider()

    def test_get_safe_creation_info_with_tracing(self):
        """
        Traces are not stored on DB, so they must be recovered from the node
        """
        random_address = Account.create().address
        self.assertIsNone(self.safe_service.get_safe_creation_info(random_address))

        InternalTxFactory(contract_address=random_address, ethereum_tx__status=0)
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
            contract_address=random_address, ethereum_tx__status=1, trace_address="0"
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
            contract_address=random_address, ethereum_tx__status=1, trace_address=""
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

    def test_decode_creation_data_multisend(self):
        # Safe created using MultiSend on BSC
        # https://bscscan.com/tx/0x35868d8794c36e1f539c9459385159ecc248cf3ebb02b98447861ad519019bc2
        data = HexBytes(
            "0x8d80ff0a000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000004f200a6b71e26c5e0845f74c812102ca7114b6a896ab2000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002041688f0b90000000000000000000000003e5c63644e683549055b9be8653de26e0b4cd36e000000000000000000000000000000000000000000000000000000000000006000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000164b63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000140000000000000000000000000f48f2b2d2a534e402487b3ee7c18c33aec0fe5e400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000004c3c38a459f0baabb763290111b66ed01b5fefa200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000eace5e6ac77210af7b26f315925df83a3f8477c0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002446a761202000000000000000000000000eace5e6ac77210af7b26f315925df83a3f8477c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000014000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001c000000000000000000000000000000000000000000000000000000000000000440d582f1300000000000000000000000065f8236309e5a99ff0d129d04e486ebce20dc7b000000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000415fc5ee3e2b15103ebbb6a4f2a41213018d7d4f8aeaaee7e4de83bae3e15bf01d0a3809560287843f70a125c5997141b2f2e6e810f3a3319d8b4d3127104424551b000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )

        results = self.safe_service._decode_creation_data(data)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.singleton, "0x3E5c63644E683549055b9Be8653de26E0B4CD36E")
        self.assertEqual(
            result.initializer,
            b"\xb6>\x80\r\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xf4\x8f+-*SN@$\x87\xb3\xee|\x18\xc3:\xec\x0f\xe5\xe4\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00L<8\xa4Y\xf0\xba\xab\xb7c)\x01\x11\xb6n\xd0\x1b_\xef\xa2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        self.assertEqual(result.salt_nonce, 0)

    def test_decode_creation_data_gelato_relay(self):
        # Safe created using Gelato Relayer on Polygon
        # https://polygonscan.com/tx/0xe4003d4ebe1a83826d4c052de106b5edaef2bd2f6bd88a956112990a9401b093
        data = HexBytes(
            "0xad718d2a0000000000000000000000004e1dcf7ad4e460cfd30791ccc4f9c8a4f820ec6700000000000000000000000000000000000000000000000000000000000000a09a97d1f69415cd1ecd2444c37a459e70f72129289bed7c233cdd0a6fa0bbc74233d71758e42fe498ef6281ead06b55cf18c82a9e7deeaefe1fc8db959b90bd01d93ec76b8b1ba6966be5c803c4e8bd3197d9e887dbea1ab2fc48873a9611fe9e00000000000000000000000000000000000000000000000000000000000002441688f0b900000000000000000000000041675c099f32341bf84bfc5382af534df5c7461a0000000000000000000000000000000000000000000000000000000000000060000000000000000000000000000000000000000000000000000000000000000300000000000000000000000000000000000000000000000000000000000001a4b63e800d00000000000000000000000000000000000000000000000000000000000001000000000000000000000000000000000000000000000000000000000000000001000000000000000000000000bd89a1ce4dde368ffab0ec35506eece0b1ffdc540000000000000000000000000000000000000000000000000000000000000140000000000000000000000000fd0732dc9e303f09fcef3a7388ad10a83459ec99000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000005afe7a11e700000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000003819b800c67be64029c1393c8b2e0d0d627dade20000000000000000000000000000000000000000000000000000000000000024fe51f64300000000000000000000000029fcb43b46531bca003ddc8fcb67ffe91900c762000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )

        results = self.safe_service._decode_creation_data(data)
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result.singleton, "0x41675C099F32341bf84BFc5382aF534df5C7461a")
        self.assertEqual(
            result.initializer,
            b"\xb6>\x80\r\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xbd\x89\xa1\xceM\xde6\x8f\xfa\xb0\xec5Pn\xec\xe0\xb1\xff\xdcT\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xfd\x072\xdc\x9e0?\t\xfc\xef:s\x88\xad\x10\xa84Y\xec\x99\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xfez\x11\xe7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x008\x19\xb8\x00\xc6{\xe6@)\xc19<\x8b.\r\rb}\xad\xe2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00$\xfeQ\xf6C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00)\xfc\xb4;FS\x1b\xca\x00=\xdc\x8f\xcbg\xff\xe9\x19\x00\xc7b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        self.assertEqual(result.salt_nonce, 3)
