# SPDX-License-Identifier: FSL-1.1-MIT
import factory
from eth_abi import encode as encode_abi
from eth_account import Account
from factory.django import DjangoModelFactory
from safe_eth.eth.utils import fast_keccak_text
from safe_eth.safe.enums import SafeOperationEnum
from safe_eth.util.util import to_0x_hex_str

from safe_transaction_service.history.tests import factories as history_factories

from .. import models
from ..constants import ERC20_TRANSFER_POLICY

ERC20_TRANSFER_SELECTOR = b"\xa9\x05\x9c\xbb"  # transfer(address,uint256)


class SafePolicyGuardFactory(DjangoModelFactory):
    class Meta:
        model = models.SafePolicyGuard

    address = factory.LazyFunction(lambda: Account.create().address)
    initial_block_number = 0
    tx_block_number = 0


class PolicyContractFactory(DjangoModelFactory):
    class Meta:
        model = models.PolicyContract

    address = factory.LazyFunction(lambda: Account.create().address)
    name = ERC20_TRANSFER_POLICY


class PolicyEngineEventFactory(DjangoModelFactory):
    ethereum_tx = factory.SubFactory(history_factories.EthereumTxFactory)
    timestamp = factory.SelfAttribute("ethereum_tx.block.timestamp")
    block_number = factory.SelfAttribute("ethereum_tx.block.number")
    log_index = factory.Sequence(lambda n: n)
    guard = factory.LazyFunction(lambda: Account.create().address)
    safe = factory.LazyFunction(lambda: Account.create().address)


class PolicyConfirmationFactory(PolicyEngineEventFactory):
    class Meta:
        model = models.PolicyConfirmation

    class Params:
        # Recipients allow list, as `ERC20TransferPolicy` expects it
        recipients = ()

    target = factory.LazyFunction(lambda: Account.create().address)
    selector = ERC20_TRANSFER_SELECTOR
    operation = SafeOperationEnum.CALL.value
    policy = factory.LazyFunction(lambda: Account.create().address)

    @factory.lazy_attribute
    def data(self):
        return encode_abi(
            ["(address,bool)[]"],
            [[(recipient, True) for recipient in self.recipients]],
        )


class PolicyRootRequestFactory(PolicyEngineEventFactory):
    class Meta:
        model = models.PolicyRootRequest

    # Prefixed per factory, so a request and an invalidation built independently never
    # share a root by accident
    root = factory.Sequence(
        lambda n: to_0x_hex_str(fast_keccak_text(f"root-request-{n}"))
    )
    valid_from = factory.SelfAttribute("ethereum_tx.block.timestamp")


class PolicyRootInvalidationFactory(PolicyEngineEventFactory):
    class Meta:
        model = models.PolicyRootInvalidation

    root = factory.Sequence(
        lambda n: to_0x_hex_str(fast_keccak_text(f"root-invalidation-{n}"))
    )
