from accounting.models import Payment, PaymentMethod, Account, FiscalYear, Invoice, InvoiceItem, \
    Journal, JournalEntry, JournalLine, LedgerSettings, Settings

from django.contrib import admin


@admin.register(Payment)
class PaymentAllocationAdmin(admin.ModelAdmin):
    pass



@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    pass


@admin.register(Account)
class FiscalYearAdmin(admin.ModelAdmin):
    pass


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    pass


@admin.register(Invoice)
class InvoiceItemAdmin(admin.ModelAdmin):
    pass


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    pass


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    pass


@admin.register(JournalEntry)
class JournalLineAdmin(admin.ModelAdmin):
    pass


@admin.register(JournalLine)
class JournalLineAdmin(admin.ModelAdmin):
    pass


@admin.register(LedgerSettings)
class LedgerSettingsAdmin(admin.ModelAdmin):
    pass


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    pass