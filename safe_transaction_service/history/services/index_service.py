import logging
from typing import List, NoReturn, OrderedDict, Union

from django.db import transaction

from hexbytes import HexBytes

from gnosis.eth import EthereumClient, EthereumClientProvider

from ..models import (EthereumBlock, EthereumTx, InternalTxDecoded,
                      MultisigConfirmation, MultisigTransaction, SafeStatus)

logger = logging.getLogger(__name__)


class TransactionNotFoundException(Exception):
    pass


class TransactionWithoutBlockException(Exception):
    pass


class IndexServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = IndexService(EthereumClientProvider())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


# TODO Test IndexService
class IndexService:
    SAFE_CONFIRMATIONS = 10

    def __init__(self, ethereum_client: EthereumClient):
        self.ethereum_client = ethereum_client

    def block_get_or_create_from_block_number(self, block_number: int):
        try:
            return EthereumBlock.get(number=block_number)
        except EthereumBlock.DoesNotExist:
            current_block_number = self.ethereum_client.current_block_number  # For reorgs
            block = self.ethereum_client.get_block(block_number)
            confirmed = (current_block_number - block['number']) >= self.SAFE_CONFIRMATIONS
            return EthereumBlock.objects.create_from_block(block, cofirmed=confirmed)

    def tx_create_or_update_from_tx_hash(self, tx_hash: str) -> 'EthereumTx':
        try:
            ethereum_tx = EthereumTx.objects.get(tx_hash=tx_hash)
            # For txs stored before being mined
            if ethereum_tx.block is None:
                tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                ethereum_block = self.block_get_or_create_from_block_number(tx_receipt['blockNumber'])
                ethereum_tx.update_with_block_and_receipt(ethereum_block, tx_receipt)
            return ethereum_tx
        except EthereumTx.DoesNotExist:
            tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
            ethereum_block = self.block_get_or_create_from_block_number(tx_receipt['blockNumber'])
            tx = self.ethereum_client.get_transaction(tx_hash)
            return EthereumTx.objects.create_from_tx_dict(tx, tx_receipt=tx_receipt, ethereum_block=ethereum_block)

    def txs_create_or_update_from_tx_hashes(self, tx_hashes: List[Union[str, bytes]]) -> List['EthereumTx']:
        # Search first in database
        ethereum_txs_dict = OrderedDict.fromkeys([HexBytes(tx_hash).hex() for tx_hash in tx_hashes])
        db_ethereum_txs = EthereumTx.objects.filter(tx_hash__in=tx_hashes).exclude(block=None)
        for db_ethereum_tx in db_ethereum_txs:
            ethereum_txs_dict[db_ethereum_tx.tx_hash] = db_ethereum_tx

        # Retrieve from the node the txs missing from database
        tx_hashes_not_in_db = [tx_hash for tx_hash, ethereum_tx in ethereum_txs_dict.items() if not ethereum_tx]
        if not tx_hashes_not_in_db:
            return list(ethereum_txs_dict.values())

        self.ethereum_client = EthereumClientProvider()

        # Get receipts for hashes not in db
        tx_receipts = []
        for tx_hash, tx_receipt in zip(tx_hashes_not_in_db,
                                       self.ethereum_client.get_transaction_receipts(tx_hashes_not_in_db)):
            tx_receipt = tx_receipt or self.ethereum_client.get_transaction_receipt(tx_hash)  # Retry fetching if failed
            if not tx_receipt:
                raise TransactionNotFoundException(f'Cannot find tx-receipt with tx-hash={HexBytes(tx_hash).hex()}')
            elif tx_receipt.get('blockNumber') is None:
                raise TransactionWithoutBlockException(f'Cannot find blockNumber for tx-receipt with '
                                                       f'tx-hash={HexBytes(tx_hash).hex()}')
            else:
                tx_receipts.append(tx_receipt)

        # Get transactions for hashes not in db
        txs = self.ethereum_client.get_transactions(tx_hashes_not_in_db)
        block_numbers = []
        for tx_hash, tx in zip(tx_hashes_not_in_db, txs):
            tx = tx or self.ethereum_client.get_transaction(tx_hash)  # Retry fetching if failed
            if not tx:
                raise TransactionNotFoundException(f'Cannot find tx with tx-hash={HexBytes(tx_hash).hex()}')
            elif tx.get('blockNumber') is None:
                raise TransactionWithoutBlockException(f'Cannot find blockNumber for tx with '
                                                       f'tx-hash={HexBytes(tx_hash).hex()}')
            block_numbers.append(tx['blockNumber'])

        blocks = self.ethereum_client.get_blocks(block_numbers)

        # Create new transactions or update them if they have no receipt
        current_block_number = self.ethereum_client.current_block_number
        for tx, tx_receipt, block in zip(txs, tx_receipts, blocks):
            confirmed = (current_block_number - block['number']) >= self.SAFE_CONFIRMATIONS
            ethereum_block = EthereumBlock.objects.get_or_create_from_block(block, confirmed=confirmed)
            try:
                ethereum_tx = EthereumTx.objects.get(tx_hash=tx['hash'])
                # For txs stored before being mined
                ethereum_tx.update_with_block_and_receipt(ethereum_block, tx_receipt)
                ethereum_txs_dict[ethereum_tx.tx_hash] = ethereum_tx
            except EthereumTx.DoesNotExist:
                ethereum_tx = EthereumTx.objects.create_from_tx_dict(tx,
                                                                     tx_receipt=tx_receipt,
                                                                     ethereum_block=ethereum_block)
                ethereum_txs_dict[HexBytes(ethereum_tx.tx_hash).hex()] = ethereum_tx
        return list(ethereum_txs_dict.values())

    @transaction.atomic
    def reindex_addresses(self, addresses: List[str]) -> NoReturn:
        """
        Given a list of safe addresses it will delete all `SafeStatus`, conflicting `MultisigTxs` and will mark
        every `InternalTxDecoded` not processed to be processed again
        :param addresses: List of checksummed addresses or queryset
        :return: Number of `SafeStatus` deleted
        """
        if not addresses:
            return 0

        safe_status_queryset = SafeStatus.objects.filter(address__in=addresses)
        internal_txs = safe_status_queryset.values('internal_tx')  # Get dangling internal txs
        MultisigTransaction.objects.exclude(ethereum_tx=None).delete()  # Remove not indexed transactions
        safe_status_queryset.delete()  # Remove all SafeStatus for that Safe
        InternalTxDecoded.objects.filter(pk__in=internal_txs).update(processed=False)  # Mark as not processed

    @transaction.atomic
    def reindex_all(self) -> NoReturn:
        MultisigConfirmation.objects.filter(signature=None).delete()  # Remove onchain confirmations
        MultisigTransaction.objects.exclude(ethereum_tx=None).delete()  # Remove not indexed transactions
        SafeStatus.objects.all().delete()
        InternalTxDecoded.objects.update(processed=False)
