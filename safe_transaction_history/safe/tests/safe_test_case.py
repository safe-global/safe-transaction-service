from ..contracts import get_safe_team_contract
from ..ethereum_service import EthereumServiceProvider
from ..safe_service import SafeServiceProvider


class TestCaseWithSafeContractMixin:
    @classmethod
    def prepare_safe_tests(cls):
        cls.safe_service = SafeServiceProvider()
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3

        cls.safe_personal_deployer = cls.w3.eth.accounts[0]
        cls.safe_personal_contract_address = cls.safe_service.deploy_master_contract(deployer_account=
                                                                                     cls.safe_personal_deployer)
        cls.safe_service.master_copy_address = cls.safe_personal_contract_address
        cls.safe_service.valid_master_copy_addresses = [cls.safe_personal_contract_address]
        cls.safe_personal_contract = get_safe_team_contract(cls.w3, cls.safe_personal_contract_address)
