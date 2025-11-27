from banking.models import BankAccount, BankStatement, BankStatementLine

from django.contrib import admin


@admin.register(BankAccount)
class BankStatementAdmin(admin.ModelAdmin):
    pass


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    pass


@admin.register(BankStatementLine)
class BankStatementLineAdmin(admin.ModelAdmin):
    pass