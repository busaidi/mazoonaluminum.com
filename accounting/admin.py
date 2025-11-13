from django.contrib import admin
from .models import Customer, Invoice, Payment, Order, OrderItem


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


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "created_at", "total_amount")
    list_filter = ("status", "created_at")
    search_fields = ("id", "customer__name", "customer__company_name")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "quantity", "unit_price", "subtotal")
    search_fields = ("product__name_en", "product__name_ar")
