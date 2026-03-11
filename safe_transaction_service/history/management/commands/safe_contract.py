# SPDX-License-Identifier: FSL-1.1-MIT
import argparse

from django.core.management.base import BaseCommand, CommandError

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from safe_eth.eth.utils import fast_to_checksum_address

from ...models import SafeContract
from ...services import IndexServiceProvider
from ...services.index_service import (
    TransactionNotFoundException,
    TransactionWithoutBlockException,
)


def _checksum_address(value: str) -> ChecksumAddress:
    try:
        return fast_to_checksum_address(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid Ethereum address: {value}") from None


def _tx_hash(value: str) -> HexBytes:
    try:
        result = HexBytes(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid transaction hash format: {value}"
        ) from None
    if len(result) != 32:
        raise argparse.ArgumentTypeError(
            f"Invalid transaction hash length: {value} (expected 32 bytes)"
        )
    return result


class Command(BaseCommand):
    help = "Handle SafeContract entries for conditional indexing"

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action", help="Action to perform")

        # Add subcommand
        add_parser = subparsers.add_parser(
            "add", help="Add a SafeContract entry manually"
        )
        add_parser.add_argument(
            "address",
            type=_checksum_address,
            help="Safe address to add",
        )
        add_parser.add_argument(
            "ethereum_tx_hash",
            type=_tx_hash,
            help="Ethereum transaction hash of the Safe creation",
        )

        # Remove subcommand
        remove_parser = subparsers.add_parser(
            "remove", help="Remove SafeContract entries"
        )
        remove_parser.add_argument(
            "addresses",
            nargs="+",
            type=_checksum_address,
            help="Safe addresses to remove",
        )

    def handle(self, *args, **options):
        action = options.get("action")

        if action == "add":
            self._handle_add(options["address"], options["ethereum_tx_hash"])
        elif action == "remove":
            self._handle_remove(options["addresses"])
        else:
            raise CommandError("Please specify an action: add or remove")

    def _handle_add(self, address: ChecksumAddress, tx_hash: HexBytes) -> None:
        if SafeContract.objects.filter(address=address).exists():
            self.stdout.write(
                self.style.WARNING(
                    f"SafeContract already exists for address: {address}"
                )
            )
            return

        index_service = IndexServiceProvider()

        self.stdout.write(f"Indexing transaction {tx_hash.hex()}...")
        try:
            ethereum_txs = index_service.txs_create_or_update_from_tx_hashes([tx_hash])
        except (TransactionNotFoundException, TransactionWithoutBlockException) as e:
            raise CommandError(str(e)) from e
        ethereum_tx = ethereum_txs[0]

        self.stdout.write(f"Creating SafeContract for {address}...")
        SafeContract.objects.create(address=address, ethereum_tx=ethereum_tx)

        from_block_number = ethereum_tx.block_id
        self.stdout.write(f"Reindexing master copies from block {from_block_number}...")
        index_service.reindex_master_copies(from_block_number, addresses=[address])

        self.stdout.write(
            f"Reindexing ERC20/ERC721 events from block {from_block_number}..."
        )
        index_service.reindex_erc20_events(from_block_number, addresses=[address])

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully added SafeContract for address={address} "
                f"with ethereum_tx={tx_hash.hex()}"
            )
        )

    def _handle_remove(self, addresses: list[ChecksumAddress]) -> None:
        removed_count = 0
        not_found_count = 0

        for address in addresses:
            deleted, _ = SafeContract.objects.filter(address=address).delete()
            if deleted:
                removed_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Removed SafeContract: {address}")
                )
            else:
                not_found_count += 1
                self.stdout.write(
                    self.style.WARNING(f"SafeContract not found: {address}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSummary: {removed_count} removed, {not_found_count} not found"
            )
        )
