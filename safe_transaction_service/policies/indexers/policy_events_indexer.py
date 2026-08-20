# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from collections import defaultdict
from collections.abc import Sequence
from functools import cached_property

from django.db.models import QuerySet

from safe_eth.eth import EthereumClient
from web3.contract.contract import ContractEvent
from web3.types import EventData, LogReceipt

from safe_transaction_service.history.indexers.events_indexer import EventsIndexer

from ..abis import SAFE_POLICY_GUARD_ABI
from ..models import (
    PolicyConfirmation,
    PolicyEngineEvent,
    PolicyRootInvalidation,
    PolicyRootRequest,
    SafePolicyGuard,
)

logger = logging.getLogger(__name__)


class PolicyEventsIndexerProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = cls.get_new_instance()

        return cls.instance

    @classmethod
    def get_new_instance(cls) -> "PolicyEventsIndexer":
        from django.conf import settings

        return PolicyEventsIndexer(EthereumClient(settings.ETHEREUM_NODE_URL))

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class PolicyEventsIndexer(EventsIndexer):
    """
    Indexes the events emitted by the `SafePolicyGuard` deployments being monitored.

    Adding an event is an entry in `EVENT_TO_MODEL` plus a model with a `from_decoded_event`.
    """

    EVENT_TO_MODEL: dict[str, type[PolicyEngineEvent]] = {
        "PolicyConfirmed": PolicyConfirmation,
        "RootConfigured": PolicyRootRequest,
        "RootInvalidated": PolicyRootInvalidation,
    }

    @cached_property
    def contract_events(self) -> list[ContractEvent]:
        contract = self.ethereum_client.w3.eth.contract(abi=SAFE_POLICY_GUARD_ABI)
        return [contract.events[event]() for event in self.EVENT_TO_MODEL]

    @property
    def database_field(self) -> str:
        return "tx_block_number"

    @property
    def database_queryset(self) -> QuerySet:
        return SafePolicyGuard.objects.all()

    def _process_decoded_element(
        self, decoded_element: EventData
    ) -> PolicyEngineEvent | None:
        model = self.EVENT_TO_MODEL[decoded_element["event"]]
        try:
            return model.from_decoded_event(decoded_element)
        except ValueError:
            logger.error(
                "Cannot build %s from event %s", model.__name__, decoded_element
            )
            return None

    def process_elements(
        self, log_receipts: Sequence[LogReceipt]
    ) -> list[PolicyEngineEvent]:
        """
        Store the policy guard events found by `find_relevant_elements`.

        Insertions ignore conflicts, so reprocessing the same logs is a no-op. That keeps
        reindexing, `blocks_to_reindex_again` and reorg recovery idempotent.

        :param log_receipts: Events to store in database
        :return: List of events already stored in database
        """
        events = super().process_elements(log_receipts)

        events_by_model: dict[type[PolicyEngineEvent], list[PolicyEngineEvent]] = (
            defaultdict(list)
        )
        for event in events:
            events_by_model[type(event)].append(event)

        for model, model_events in events_by_model.items():
            model.objects.bulk_create(model_events, ignore_conflicts=True)

        return events
