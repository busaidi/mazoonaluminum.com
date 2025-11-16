# ledger/forms.py
from django import forms
from django.forms import inlineformset_factory
from .models import Account, JournalEntry, JournalLine


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ["code", "name", "type", "parent", "is_active", "allow_settlement"]



class JournalEntryForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ["date", "reference", "description"]


class JournalLineForm(forms.ModelForm):
    class Meta:
        model = JournalLine
        fields = ["account", "description", "debit", "credit"]


JournalLineFormSet = inlineformset_factory(
    JournalEntry,
    JournalLine,
    form=JournalLineForm,
    extra=3,
    can_delete=True,
)


class TrialBalanceFilterForm(forms.Form):
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)


class AccountLedgerFilterForm(forms.Form):
    account = forms.ModelChoiceField(queryset=Account.objects.all())
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)
