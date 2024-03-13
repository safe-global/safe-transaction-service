import binascii

from django.core.management.base import BaseCommand
from ...models import SafeMasterCopy

class Command(BaseCommand):
    help = "Insert SafeMasterCopy objects"

    def add_arguments(self, parser):
        parser.add_argument("--address", help="SafeMasterCopy address", required=True)
        parser.add_argument("--initial-block-number", help="Initial block number", required=False, default=0)
        parser.add_argument("--tx-block-number", help="Transaction block number", required=False, default=None)
        parser.add_argument("--safe-version", help="Safe Version", required=False, default="1.3.0")
        parser.add_argument("--l2", help="Address on L2", required=False, default=False)
        parser.add_argument("--deployer", help="Deployer", required=False, default="Safe")

    def handle(self, *args, **options):
        mastercopy_address = options["address"]
        initial_block_number = options["initial_block_number"]
        tx_block_number = options["tx_block_number"]
        version = options["safe_version"]
        l2 = options["l2"]
        deployer = options["deployer"]
        
        SafeMasterCopy.objects.create(
            address=mastercopy_address,
            initial_block_number=initial_block_number,
            tx_block_number=tx_block_number,
            version=version,
            l2=l2,
            deployer=deployer,
        )

        self.stdout.write(self.style.SUCCESS(f"Created SafeMasterCopy for {mastercopy_address}"))