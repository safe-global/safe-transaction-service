import time

from django.core.management.base import BaseCommand

from safe_transaction_service.history.indexers import SafeEventsIndexerProvider
from safe_transaction_service.history.models import SafeMasterCopy


class Command(BaseCommand):
    help = "Force reindexing of erc20/721 events"

    def handle(self, *args, **options):
        SafeMasterCopy("0x29fcB43b46531BcA003ddC8FCB67FFE91900C762").save()
        SafeMasterCopy("0x3E5c63644E683549055b9Be8653de26E0B4CD36E").save()
        addresses = set(SafeMasterCopy.objects.all().values_list("address", flat=True))
        indexer = SafeEventsIndexerProvider()

        start_block = 1799327
        relevant = indexer.find_relevant_elements(
            addresses, start_block, start_block + 100
        )
        start = time.time()
        indexer.process_elements(relevant)
        print(f"Total time for {len(relevant)} {time.time() - start}")
        # relevant = indexer.find_relevant_elements(
        #            addresses, start_block, start_block + 50
        #        )
        # decoded_elements = indexer.decode_elements(relevant)
        # tx_hashes = OrderedDict.fromkeys(
        #    [event["transactionHash"] for event in relevant]
        # ).keys()
        # indexer.index_service.txs_create_or_update_from_tx_hashes(tx_hashes)
        # start = time.time()
        # for decoded_element in decoded_elements:
        #    indexer._process_decoded_element(decoded_element)
