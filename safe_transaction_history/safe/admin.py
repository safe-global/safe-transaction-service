from django.contrib import admin

from .models import MultisigTransaction, MultisigConfirmation

admin.site.register([MultisigTransaction, MultisigConfirmation])