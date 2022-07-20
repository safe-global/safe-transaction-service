import os.path
import tempfile
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

from django.core.management import CommandError, call_command
from django.test import TestCase

from django_celery_beat.models import PeriodicTask

from gnosis.eth.ethereum_client import EthereumClient, EthereumNetwork

from ..indexers import Erc20EventsIndexer, InternalTxIndexer, SafeEventsIndexer
from ..models import ProxyFactory, SafeMasterCopy
from ..services import IndexServiceProvider
from ..tasks import logger as task_logger
from .factories import (
    MultisigTransactionFactory,
    SafeContractFactory,
    SafeMasterCopyFactory,
)


class TestCommands(TestCase):
    @mock.patch.object(EthereumClient, "get_network", autospec=True)
    def _test_setup_service(
        self,
        ethereum_network: EthereumNetwork,
        ethereum_client_get_network_mock: MagicMock,
    ):
        command = "setup_service"
        ethereum_client_get_network_mock.return_value = ethereum_network
        buf = StringIO()
        self.assertEqual(SafeMasterCopy.objects.count(), 0)
        self.assertEqual(ProxyFactory.objects.count(), 0)
        self.assertEqual(PeriodicTask.objects.count(), 0)

        call_command(command, stdout=buf)
        self.assertIn(
            f"Setting up {ethereum_network.name} safe addresses", buf.getvalue()
        )
        self.assertIn(
            f"Setting up {ethereum_network.name} proxy factory addresses",
            buf.getvalue(),
        )
        self.assertIn("Created Periodic Task", buf.getvalue())
        self.assertNotIn("was already created", buf.getvalue())
        self.assertGreater(SafeMasterCopy.objects.count(), 0)
        self.assertGreater(ProxyFactory.objects.count(), 0)
        self.assertGreater(PeriodicTask.objects.count(), 0)

        # Check last master copy was created
        last_master_copy_address = "0x6851D6fDFAfD08c0295C392436245E5bc78B0185"
        last_master_copy = SafeMasterCopy.objects.get(address=last_master_copy_address)
        self.assertGreater(last_master_copy.initial_block_number, 0)
        self.assertGreater(last_master_copy.tx_block_number, 0)

        # Check last proxy factory was created
        last_proxy_factory_address = "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B"
        last_proxy_factory = ProxyFactory.objects.get(
            address=last_proxy_factory_address
        )
        self.assertGreater(last_proxy_factory.initial_block_number, 0)
        self.assertGreater(last_proxy_factory.tx_block_number, 0)

        buf = StringIO()
        call_command(command, stdout=buf)
        self.assertIn(
            f"Setting up {ethereum_network.name} safe addresses", buf.getvalue()
        )
        self.assertIn(
            f"Setting up {ethereum_network.name} proxy factory addresses",
            buf.getvalue(),
        )
        self.assertIn("Removing old tasks", buf.getvalue())
        self.assertIn("Old tasks were removed", buf.getvalue())
        self.assertIn("Created Periodic Task", buf.getvalue())

    def test_add_webhook(self):
        command = "add_webhook"

        with self.assertRaisesMessage(
            CommandError, "the following arguments are required: --url"
        ):
            call_command(command)

        buf = StringIO()
        call_command(command, "--url=http://docker-url", stdout=buf)
        self.assertIn("Created webhook for", buf.getvalue())

        buf = StringIO()
        call_command(command, "--url=https://test-url.com", stdout=buf)
        self.assertIn("Created webhook for", buf.getvalue())

    def test_index_erc20(self):
        command = "index_erc20"
        buf = StringIO()
        with self.assertLogs(logger=task_logger) as cm:
            call_command(command, stdout=buf)
            self.assertIn("No addresses to process", cm.output[0])

        buf = StringIO()
        call_command(command, "--block-process-limit=10", stdout=buf)
        self.assertIn("Setting block-process-limit to 10", buf.getvalue())

        buf = StringIO()
        call_command(
            command,
            "--block-process-limit=10",
            "--block-process-limit-max=15",
            stdout=buf,
        )
        self.assertIn("Setting block-process-limit to 10", buf.getvalue())
        self.assertIn("Setting block-process-limit-max to 15", buf.getvalue())

        with self.assertLogs(logger=task_logger) as cm:
            safe_contract = SafeContractFactory()
            buf = StringIO()
            call_command(command, stdout=buf)
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {[safe_contract.address]}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

        with self.assertLogs(logger=task_logger) as cm:
            safe_contract_2 = SafeContractFactory()
            buf = StringIO()
            call_command(command, f"--addresses={safe_contract_2.address}", stdout=buf)
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {[safe_contract_2.address]}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

        # Test sync task call
        with self.assertLogs(logger=task_logger) as cm:
            safe_contract_2 = SafeContractFactory()
            buf = StringIO()
            call_command(
                command, f"--addresses={safe_contract_2.address}", "--sync", stdout=buf
            )
            self.assertIn(
                f"Start indexing of erc20/721 events for out of sync addresses {[safe_contract_2.address]}",
                cm.output[0],
            )
            self.assertIn(
                "Indexing of erc20/721 events for out of sync addresses task processed 0 events",
                cm.output[1],
            )

    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_reindex_master_copies(self, current_block_number_mock: PropertyMock):
        logger_name = "safe_transaction_service.history.services.index_service"
        current_block_number_mock.return_value = 1000
        command = "reindex_master_copies"

        with self.assertRaisesMessage(
            CommandError, "the following arguments are required: --from-block-number"
        ):
            call_command(command)

        buf = StringIO()
        with self.assertLogs(logger_name, level="WARNING") as cm:
            call_command(
                command,
                "--block-process-limit=11",
                "--from-block-number=76",
                stdout=buf,
            )
            self.assertIn("Setting block-process-limit to 11", buf.getvalue())
            self.assertIn("Setting from-block-number to 76", buf.getvalue())
            self.assertIn("No addresses to process", cm.output[0])

        safe_master_copy = SafeMasterCopyFactory(l2=False)
        buf = StringIO()
        with self.assertLogs(logger_name, level="INFO") as cm:
            with mock.patch.object(
                InternalTxIndexer, "find_relevant_elements", return_value=[]
            ) as find_relevant_elements_mock:
                IndexServiceProvider.del_singleton()
                from_block_number = 100
                block_process_limit = 500
                call_command(
                    command,
                    f"--block-process-limit={block_process_limit}",
                    f"--from-block-number={from_block_number}",
                    stdout=buf,
                )
                self.assertIn(
                    f"Start reindexing addresses {[safe_master_copy.address]}",
                    cm.output[0],
                )
                self.assertIn("found 0 traces/events", cm.output[1])
                self.assertIn(
                    f"End reindexing addresses {[safe_master_copy.address]}",
                    cm.output[3],
                )
                find_relevant_elements_mock.assert_any_call(
                    [safe_master_copy.address],
                    from_block_number,
                    from_block_number + block_process_limit - 1,
                )
                find_relevant_elements_mock.assert_any_call(
                    [safe_master_copy.address],
                    from_block_number + block_process_limit,
                    current_block_number_mock.return_value,
                )
                self.assertEqual(find_relevant_elements_mock.call_count, 2)

        with self.settings(ETH_L2_NETWORK=True):
            IndexServiceProvider.del_singleton()
            buf = StringIO()
            with self.assertLogs(logger_name, level="WARNING") as cm:
                call_command(command, "--from-block-number=71", stdout=buf)
            self.assertIn("No addresses to process", cm.output[0])

            with self.assertLogs(logger_name, level="INFO") as cm:
                with mock.patch.object(
                    SafeEventsIndexer, "find_relevant_elements", return_value=[]
                ) as find_relevant_elements_mock:
                    safe_l2_master_copy = SafeMasterCopyFactory(l2=True)
                    buf = StringIO()
                    from_block_number = 200
                    block_process_limit = 500
                    call_command(
                        command,
                        f"--block-process-limit={block_process_limit}",
                        f"--from-block-number={from_block_number}",
                        stdout=buf,
                    )
                    self.assertIn(
                        f"Start reindexing addresses {[safe_l2_master_copy.address]}",
                        cm.output[0],
                    )
                    self.assertIn("found 0 traces/events", cm.output[1])
                    self.assertIn(
                        f"End reindexing addresses {[safe_l2_master_copy.address]}",
                        cm.output[3],
                    )
                    find_relevant_elements_mock.assert_any_call(
                        [safe_l2_master_copy.address],
                        from_block_number,
                        from_block_number + block_process_limit - 1,
                    )
                    find_relevant_elements_mock.assert_any_call(
                        [safe_l2_master_copy.address],
                        from_block_number + block_process_limit,
                        current_block_number_mock.return_value,
                    )
                    self.assertEqual(find_relevant_elements_mock.call_count, 2)
        IndexServiceProvider.del_singleton()

    @mock.patch.object(
        EthereumClient, "current_block_number", new_callable=PropertyMock
    )
    def test_reindex_erc20_events(self, current_block_number_mock: PropertyMock):
        logger_name = "safe_transaction_service.history.services.index_service"
        current_block_number_mock.return_value = 1000
        command = "reindex_erc20"

        with self.assertRaisesMessage(
            CommandError, "the following arguments are required: --from-block-number"
        ):
            call_command(command)

        buf = StringIO()
        with self.assertLogs(logger_name, level="WARNING") as cm:
            call_command(
                command,
                "--block-process-limit=11",
                "--from-block-number=76",
                stdout=buf,
            )
            self.assertIn("Setting block-process-limit to 11", buf.getvalue())
            self.assertIn("Setting from-block-number to 76", buf.getvalue())
            self.assertIn("No addresses to process", cm.output[0])

        safe_contract = SafeContractFactory()
        buf = StringIO()
        with self.assertLogs(logger_name, level="INFO") as cm:
            with mock.patch.object(
                Erc20EventsIndexer, "find_relevant_elements", return_value=[]
            ) as find_relevant_elements_mock:
                IndexServiceProvider.del_singleton()
                from_block_number = 100
                block_process_limit = 500
                call_command(
                    command,
                    f"--block-process-limit={block_process_limit}",
                    f"--from-block-number={from_block_number}",
                    stdout=buf,
                )
                self.assertIn(
                    f"Start reindexing addresses {[safe_contract.address]}",
                    cm.output[0],
                )
                self.assertIn("found 0 traces/events", cm.output[1])
                self.assertIn(
                    f"End reindexing addresses {[safe_contract.address]}",
                    cm.output[3],
                )
                find_relevant_elements_mock.assert_any_call(
                    [safe_contract.address],
                    from_block_number,
                    from_block_number + block_process_limit - 1,
                )
                find_relevant_elements_mock.assert_any_call(
                    [safe_contract.address],
                    from_block_number + block_process_limit,
                    current_block_number_mock.return_value,
                )
                self.assertEqual(find_relevant_elements_mock.call_count, 2)
        IndexServiceProvider.del_singleton()

    def test_setup_service_mainnet(self):
        self._test_setup_service(EthereumNetwork.MAINNET)

        # Check last master copy was created
        last_master_copy_address = "0x6851D6fDFAfD08c0295C392436245E5bc78B0185"
        last_master_copy_initial_block = 10329734
        last_master_copy = SafeMasterCopy.objects.get(address=last_master_copy_address)
        self.assertEqual(
            last_master_copy.initial_block_number, last_master_copy_initial_block
        )
        self.assertEqual(
            last_master_copy.tx_block_number, last_master_copy_initial_block
        )

        # Check last proxy factory was created
        last_proxy_factory_address = "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B"
        last_proxy_factory_initial_block = 9084508
        last_proxy_factory = ProxyFactory.objects.get(
            address=last_proxy_factory_address
        )
        self.assertEqual(
            last_proxy_factory.initial_block_number, last_proxy_factory_initial_block
        )
        self.assertEqual(
            last_proxy_factory.tx_block_number, last_proxy_factory_initial_block
        )

        self.assertEqual(SafeMasterCopy.objects.count(), 8)
        self.assertEqual(SafeMasterCopy.objects.l2().count(), 1)
        self.assertEqual(ProxyFactory.objects.count(), 4)

    def test_setup_service_rinkeby(self):
        self._test_setup_service(EthereumNetwork.RINKEBY)

    def test_setup_service_goerli(self):
        self._test_setup_service(EthereumNetwork.GOERLI)

    def test_setup_service_kovan(self):
        self._test_setup_service(EthereumNetwork.KOVAN)

    @mock.patch.object(EthereumClient, "get_network", autospec=True)
    def test_setup_service_not_valid_network(
        self, ethereum_client_get_network_mock: MagicMock
    ):
        command = "setup_service"
        for return_value in (EthereumNetwork.ROPSTEN, EthereumNetwork.UNKNOWN):
            ethereum_client_get_network_mock.return_value = return_value
            buf = StringIO()
            call_command(command, stdout=buf)
            self.assertIn("Cannot detect a valid ethereum-network", buf.getvalue())

    def test_export_multisig_tx_data(self):
        with tempfile.TemporaryDirectory() as tmpdirname:
            command = "export_multisig_tx_data"
            arguments = "--file-name=" + os.path.join(tmpdirname, "result.csv")
            buf = StringIO()
            call_command(command, arguments, stdout=buf)
            self.assertIn("Start exporting of 0", buf.getvalue())

            MultisigTransactionFactory(origin="something")
            MultisigTransactionFactory(
                origin="another-something", ethereum_tx=None
            )  # Will not be exported
            MultisigTransactionFactory(origin=None)  # Will not be exported
            buf = StringIO()
            call_command(command, arguments, stdout=buf)
            self.assertIn("Start exporting of 1", buf.getvalue())
