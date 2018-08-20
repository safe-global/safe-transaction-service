from django.contrib import admin

from .models import MultisigConfirmation, MultisigTransaction

admin.site.register([MultisigTransaction, MultisigConfirmation])
