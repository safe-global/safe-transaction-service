from typing import Optional, Sequence

from eth_typing import ChecksumAddress

from ...services import IndexServiceProvider
from .reindex_master_copies import Command as ReindexMasterCopiesCommand


class Command(ReindexMasterCopiesCommand):
    help = "Force reindexing of erc20/721 events"

    def reindex(
        self,
        from_block_number: int,
        block_process_limit: Optional[int],
        addresses: Optional[Sequence[ChecksumAddress]],
    ) -> None:
        return IndexServiceProvider().reindex_erc20_events(
            from_block_number,
            block_process_limit=block_process_limit,
            addresses=addresses,
        )
