# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0097_internaltxdecoded_safe_address_processed"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="internaltxdecoded",
            index=models.Index(
                condition=models.Q(function_name="setup"),
                fields=["safe_address"],
                name="history_decoded_setup_idx",
            ),
        ),
    ]

