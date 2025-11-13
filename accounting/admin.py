from django.contrib import admin
from .models import Customer, Invoice, Payment


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "company_name", "phone", "email", "total_invoiced", "total_paid", "balance")
    search_fields = ("name", "company_name", "phone", "email")
    list_filter = ("created_at",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "customer", "issued_at", "due_date", "total_amount", "paid_amount", "status")
    list_filter = ("status", "issued_at")
    search_fields = ("number", "customer__name", "customer__company_name")
    date_hierarchy = "issued_at"
    autocomplete_fields = ("customer",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("customer", "invoice", "date", "amount", "method")
    list_filter = ("method", "date")
    search_fields = ("customer__name", "invoice__number")
    autocomplete_fields = ("customer", "invoice")
