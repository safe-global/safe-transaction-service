"""
Generated manually for pending_for_safe query optimization

Now update the processed records, will take a lot of time but it's necessary for reindexing/reprocessing
"""

from django.db import migrations
from web3.constants import ADDRESS_ZERO

# Placeholder address used as default before backfill
PLACEHOLDER_ADDRESS = ADDRESS_ZERO

def populate_safe_address(apps, schema_editor):
    """
    Populate safe_address from internal_tx._from for existing records.
    Uses a single efficient UPDATE query.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE history_internaltxdecoded 
            SET safe_address = history_internaltx._from
            FROM history_internaltx 
            WHERE history_internaltxdecoded.internal_tx_id = history_internaltx.id
            AND history_internaltxdecoded.safe_address = %s
        """, [bytes.fromhex(PLACEHOLDER_ADDRESS[2:])])


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0096_internaltxdecoded_safe_address'),
    ]

    operations = [
        migrations.RunPython(
            populate_safe_address,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
