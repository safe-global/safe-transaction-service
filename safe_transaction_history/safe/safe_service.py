from logging import getLogger
from typing import List, Tuple

import eth_abi
from ethereum.utils import sha3
from hexbytes import HexBytes

from django_eth.constants import NULL_ADDRESS

from .contracts import (get_paying_proxy_contract,
                        get_paying_proxy_deployed_bytecode,
                        get_safe_team_contract)
from .ethereum_service import EthereumServiceProvider
from .safe_creation_tx import SafeCreationTx

logger = getLogger(__name__)


class InvalidMultisigTx(Exception):
    pass


class InvalidProxyContract(Exception):
    pass


class InvalidMasterCopyAddress(Exception):
    pass


class SafeServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = SafeService(settings.SAFE_TEAM_CONTRACT_ADDRESS,
                                       settings.SAFE_TEAM_VALID_CONTRACT_ADDRESSES,
                                       settings.SAFE_TX_SENDER_PRIVATE_KEY,
                                       settings.SAFE_FUNDER_PRIVATE_KEY)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeService:
    def __init__(self, master_copy_address: str, valid_master_copy_addresses: List[str],
                 tx_sender_private_key: str=None, funder_private_key: str=None):
        self.ethereum_service = EthereumServiceProvider()
        self.w3 = self.ethereum_service.w3
        self.master_copy_address = master_copy_address
        self.valid_master_copy_addresses = valid_master_copy_addresses
        self.tx_sender_private_key = tx_sender_private_key
        self.funder_private_key = funder_private_key
        if self.funder_private_key:
            self.funder_address = self.ethereum_service.private_key_to_address(self.funder_private_key)
        else:
            self.funder_address = None

    def build_safe_creation_tx(self, s: int, owners: List[str], threshold: int, gas_price: int=None) -> SafeCreationTx:

        gas_price = gas_price if gas_price else self.ethereum_service.get_fast_gas_price()

        safe_creation_tx = SafeCreationTx(w3=self.w3,
                                          owners=owners,
                                          threshold=threshold,
                                          signature_s=s,
                                          master_copy=self.master_copy_address,
                                          gas_price=gas_price,
                                          funder=self.funder_address)

        assert safe_creation_tx.contract_creation_tx.nonce == 0
        return safe_creation_tx

    def deploy_master_contract(self, deployer_account=None, deployer_private_key=None) -> str:
        """
        Deploy master contract. Takes deployer_account (if unlocked in the node) or the deployer private key
        :param deployer_account: Unlocked ethereum account
        :param deployer_private_key: Private key of an ethereum account
        :return: deployed contract address
        """
        assert deployer_account or deployer_private_key

        safe_team_contract = get_safe_team_contract(self.w3)
        constructor = safe_team_contract.constructor()
        gas = 5125602

        if deployer_account:
            tx_hash = constructor.transact({'from': deployer_account, 'gas': gas})
        else:
            deployer_account = self.ethereum_service.private_key_to_address(deployer_private_key)
            tx = constructor.transact({'gas': gas}).buildTransaction()
            signed_tx = self.w3.eth.account.signTransaction(tx, private_key=deployer_private_key)
            tx_hash = self.ethereum_service.send_raw_transaction(signed_tx.rawTransaction)

        tx_receipt = self.ethereum_service.get_transaction_receipt(tx_hash, timeout=60)

        contract_address = tx_receipt.contractAddress
        logger.info("Deployed Safe Master Contract=%s by %s", contract_address, deployer_account)
        return contract_address

    def deploy_proxy_contract(self, deployer_account=None, deployer_private_key=None) -> str:
        """
        Deploy proxy contract. Takes deployer_account (if unlocked in the node) or the deployer private key
        :param deployer_account: Unlocked ethereum account
        :param deployer_private_key: Private key of an ethereum account
        :return: deployed contract address
        """
        assert deployer_account or deployer_private_key

        safe_proxy_contract = get_paying_proxy_contract(self.w3)
        constructor = safe_proxy_contract.constructor(self.master_copy_address, b'', NULL_ADDRESS, NULL_ADDRESS, 0)
        gas = 5125602

        if deployer_account:
            tx_hash = constructor.transact({'from': deployer_account, 'gas': gas})
        else:
            tx = constructor.transact({'gas': gas}).buildTransaction()
            signed_tx = self.w3.eth.account.signTransaction(tx, private_key=deployer_private_key)
            tx_hash = self.ethereum_service.send_raw_transaction(signed_tx.rawTransaction)

        tx_receipt = self.ethereum_service.get_transaction_receipt(tx_hash, timeout=60)

        contract_address = tx_receipt.contractAddress
        return contract_address

    def check_master_copy(self, address) -> bool:
        master_copy_address = self.retrieve_master_copy_address(address)
        return master_copy_address in self.valid_master_copy_addresses

    def check_proxy_code(self, address) -> bool:
        """
        Check if proxy is valid
        :param address: address of the proxy
        :return: True if proxy is valid, False otherwise
        """
        deployed_proxy_code = self.w3.eth.getCode(address)
        proxy_code = get_paying_proxy_deployed_bytecode()

        return deployed_proxy_code == proxy_code

    def get_contract(self, safe_address):
        return get_safe_team_contract(self.w3, address=safe_address)

    def get_gas_token(self):
        return NULL_ADDRESS

    def retrieve_master_copy_address(self, safe_address) -> str:
        return get_paying_proxy_contract(self.w3, safe_address).functions.implementation().call()

    def retrieve_nonce(self, safe_address) -> int:
        return self.get_contract(safe_address).functions.nonce().call()

    def retrieve_threshold(self, safe_address) -> int:
        return self.get_contract(safe_address).functions.getThreshold().call()

    def estimate_tx_gas(self, safe_address: str, to: str, value: int, data: bytes, operation: int) -> int:
        try:
            self.get_contract(safe_address).functions.requiredTxGas(
                to,
                value,
                data,
                operation
            ).call({'from': safe_address})
            raise ValueError
        except ValueError as e:
            data = e.args[0]['data']
            key = list(data.keys())[0]
            return_data = data[key]['return']
            # 2 - 0x
            # 8 - error method id
            # 64 - position
            # 64 - length
            estimated_gas = int(return_data[138:], 16)
            # Add 10k else we will fail in case of nested calls
            return estimated_gas + 10000

    def estimate_tx_data_gas(self, safe_address: str, to: str, value: int, data: bytes,
                             operation: int, estimate_tx_gas: int):
        paying_proxy_contract = self.get_contract(safe_address)
        threshold = paying_proxy_contract.functions.getThreshold().call()
        nonce = paying_proxy_contract.functions.nonce().call()

        # Calculate gas for signatures
        signature_gas = threshold * (1 * 68 + 2 * 32 * 68)

        safe_tx_gas = estimate_tx_gas
        data_gas = 0
        gas_price = 1
        gas_token = NULL_ADDRESS
        signatures = b''
        data = paying_proxy_contract.functions.execTransactionAndPaySubmitter(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            signatures,
        ).buildTransaction({
            'gas': 1,
            'gasPrice': 1,
            'nonce': nonce
        })['data']

        data_gas = signature_gas + self.ethereum_service.estimate_data_gas(data)

        # Add aditional gas costs
        if data_gas > 65536:
            data_gas += 64
        else:
            data_gas += 128

        data_gas += 32000  # Base tx costs, transfer costs...

        return data_gas

    def send_multisig_tx(self,
                         safe_address: str, to: str, value: int, data: bytes,
                         operation: int, safe_tx_gas: int, data_gas: int, gas_price: int,
                         gas_token: str,
                         signatures: bytes,
                         tx_sender_private_key=None,
                         tx_gas=None,
                         tx_gas_price=None) -> Tuple[str, any]:

        # Make sure proxy contract is ours
        if not self.check_proxy_code(safe_address):
            raise InvalidProxyContract(safe_address)

        # Make sure proxy contract is ours
        if not self.check_master_copy(safe_address):
            raise InvalidMasterCopyAddress

        data = data or b''
        gas_token = gas_token or NULL_ADDRESS
        to = to or NULL_ADDRESS

        tx_gas = tx_gas or (safe_tx_gas + data_gas) * 2
        # Use original tx gas_price if not provided
        tx_gas_price = tx_gas_price or gas_price
        tx_sender_private_key = tx_sender_private_key or self.tx_sender_private_key

        safe_contract = get_safe_team_contract(self.w3, address=safe_address)
        success = safe_contract.functions.execTransactionAndPaySubmitter(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            signatures,
        ).call()

        if not success:
            raise InvalidMultisigTx

        tx_sender_address = self.ethereum_service.private_key_to_address(tx_sender_private_key)

        tx = safe_contract.functions.execTransactionAndPaySubmitter(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            signatures,
        ).buildTransaction({
            'from': tx_sender_address,
            'gas': tx_gas,
            'gasPrice': tx_gas_price,
            'nonce': self.ethereum_service.get_nonce_for_account(tx_sender_address)
        })

        tx_signed = self.w3.eth.account.signTransaction(tx, tx_sender_private_key)

        return self.w3.eth.sendRawTransaction(tx_signed.rawTransaction), tx

    @staticmethod
    def get_hash_for_safe_tx(safe_address: str, to: str, value: int, data: bytes,
                             operation: int, nonce: int) -> HexBytes:

        data = data or b''
        to = to or NULL_ADDRESS

        data_bytes = (
                bytes.fromhex('19') +
                bytes.fromhex('00') +
                HexBytes(safe_address) +
                HexBytes(to) +
                eth_abi.encode_single('uint256', value) +
                data +  # Data is always zero-padded to be even on solidity. So, 0x1 becomes 0x01
                operation.to_bytes(1, byteorder='big') +  # abi.encodePacked packs it on 1 byte
                eth_abi.encode_single('uint256', nonce)
        )

        return HexBytes(sha3(data_bytes))

    def check_hash(self, tx_hash: str, signatures: bytes, owners: List[str]) -> bool:
        for i, owner in enumerate(sorted(owners, key=lambda x: x.lower())):
            v, r, s = self.signature_split(signatures, i)
            if self.ethereum_service.get_signing_address(tx_hash, v, r, s) != owner:
                return False
        return True

    @staticmethod
    def signature_split(signatures: bytes, pos: int) -> Tuple[int, int, int]:
        """
        :param signatures: signatures in form of {bytes32 r}{bytes32 s}{uint8 v}
        :param pos: position of the signature
        :return: Tuple with v, r, s
        """
        signature_pos = 65 * pos
        v = signatures[64 + signature_pos]
        r = int.from_bytes(signatures[signature_pos:32 + signature_pos], 'big')
        s = int.from_bytes(signatures[32 + signature_pos:64 + signature_pos], 'big')

        return v, r, s

    @classmethod
    def signatures_to_bytes(cls, signatures: List[Tuple[int, int, int]]) -> bytes:
        """
        Convert signatures to bytes
        :param signatures: list of v, r, s
        :return: 65 bytes per signature
        """
        return b''.join([cls.signature_to_bytes(vrs) for vrs in signatures])

    @staticmethod
    def signature_to_bytes(vrs: Tuple[int, int, int]) -> bytes:
        """
        Convert signature to bytes
        :param vrs: tuple of v, r, s
        :return: signature in form of {bytes32 r}{bytes32 s}{uint8 v}
        """

        byte_order = 'big'

        v, r, s = vrs

        return (r.to_bytes(32, byteorder=byte_order) +
                s.to_bytes(32, byteorder=byte_order) +
                v.to_bytes(1, byteorder=byte_order))
