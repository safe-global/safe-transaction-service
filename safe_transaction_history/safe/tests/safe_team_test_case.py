import logging

from django.conf import settings

from django_eth.constants import NULL_ADDRESS

from ..contracts import get_safe_team_contract
from ..ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_creation_tx import SafeCreationTx
from gnosis.safe.safe_service import SafeTeamServiceProvider
from .factories import generate_valid_s

logger = logging.getLogger(__name__)


class TestCaseWithSafeTeamContractMixin:

    GAS_PRICE = settings.SAFE_GAS_PRICE
    CALL_OPERATION = 0

    @classmethod
    def prepare_safe_tests(cls):
        cls.safe_service = SafeTeamServiceProvider()
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3

        cls.safe_team_deployer_account = cls.w3.eth.accounts[0]
        cls.safe_team_contract_address = cls.safe_service.deploy_master_contract(deployer_account=
                                                                                 cls.safe_team_deployer_account)
        cls.safe_service.master_copy_address = cls.safe_team_contract_address
        cls.safe_service.valid_master_copy_addresses = [cls.safe_team_contract_address]
        cls.safe_team_contract = get_safe_team_contract(cls.w3, cls.safe_team_contract_address)

    def deploy_safe(self, max_owners=3):
        fund_amount = 100000000000000000 # 0.1 ETH
        # Create Safe on blockchain
        s = generate_valid_s()
        funder = self.w3.eth.accounts[0]
        owners = self.w3.eth.accounts[0:max_owners]
        threshold = len(owners) - 1
        gas_price = self.GAS_PRICE

        safe_builder = SafeCreationTx(w3=self.w3,
                                      owners=owners,
                                      threshold=threshold,
                                      signature_s=s,
                                      master_copy=self.safe_team_contract_address,
                                      gas_price=gas_price,
                                      funder=NULL_ADDRESS)

        tx_hash = self.w3.eth.sendTransaction({
            'from': funder,
            'to': safe_builder.deployer_address,
            'value': safe_builder.payment
        })

        self.assertIsNotNone(tx_hash)

        logger.info("Create proxy contract with address %s", safe_builder.safe_address)

        tx_hash = self.w3.eth.sendRawTransaction(safe_builder.raw_tx)
        tx_receipt = self.w3.eth.waitForTransactionReceipt(tx_hash)

        safe_address = tx_receipt.contractAddress
        safe_instance = get_safe_team_contract(self.w3, safe_address)

        self.assertEqual(safe_instance.functions.getThreshold().call(), threshold)
        self.assertEqual(safe_instance.functions.getOwners().call(), owners)

        tx_hash = self.w3.eth.sendTransaction({
            'from': funder,
            'to': safe_address,
            'value': fund_amount
        })

        return safe_address, safe_instance, owners, funder, fund_amount, threshold
