# Generated manually for pending_for_safe query optimization

from django.db import migrations, models
from django.db.models import Q
from safe_eth.eth.django.models import EthereumAddressBinaryField
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
        ("history", "0095_remove_internaltx_history_internaltx_value_idx_and_more"),
    ]

    operations = [
        # Add the new field with a placeholder default (non-null)
        migrations.AddField(
            model_name="internaltxdecoded",
            name="safe_address",
            field=EthereumAddressBinaryField(default=PLACEHOLDER_ADDRESS),
            preserve_default=False,
        ),
        # Populate existing records from internal_tx._from
        migrations.RunPython(
            populate_safe_address,
            reverse_code=migrations.RunPython.noop,
        ),
        # Add optimized partial index for pending_for_safe query
        # Filters by safe_address for unprocessed records only
        migrations.AddIndex(
            model_name="internaltxdecoded",
            index=models.Index(
                condition=Q(processed=False),
                fields=["safe_address"],
                name="history_decoded_safe_pending_idx",
            ),
        ),
    ]
