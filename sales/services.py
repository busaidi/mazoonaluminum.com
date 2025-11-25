# sales/services.py
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import SalesDocument, SalesLine

# نحاول استيراد نماذج الفواتير من تطبيق المحاسبة (accounting)
try:
    from accounting.models import Invoice
except Exception:  # pragma: no cover - في حال عدم وجود تطبيق المحاسبة
    Invoice = None
    InvoiceLine = None
else:
    try:
        from accounting.models import InvoiceLine
    except Exception:  # pragma: no cover - في حال عدم وجود InvoiceLine
        InvoiceLine = None


# ============================================================
# تحويل عرض السعر → طلب بيع
# ============================================================


@transaction.atomic
def convert_quotation_to_order(quotation: SalesDocument) -> SalesDocument:
    """
    يحوّل عرض سعر (QUOTATION) إلى طلب بيع (ORDER).

    - لو تم التحويل سابقاً يرجّع نفس الطلب القديم.
    - ينسخ كل البنود كما هي.
    - يعيد حساب الإجمالي باستخدام recompute_totals().
    - يحدّث حالة عرض السعر إلى "مؤكد".
    """

    if not quotation.is_quotation:
        raise ValueError("Sales document is not a quotation.")

    if not quotation.can_be_converted_to_order():
        raise ValueError("This quotation cannot be converted to an order.")

    # لو تم تحويله سابقاً، رجّع نفس الأوردر
    existing_order = quotation.child_documents.filter(
        kind=SalesDocument.Kind.ORDER
    ).first()
    if existing_order:
        return existing_order

    # إنشاء طلب جديد مبني على عرض السعر
    order = SalesDocument.objects.create(
        kind=SalesDocument.Kind.ORDER,
        status=SalesDocument.Status.CONFIRMED,
        contact=quotation.contact,
        date=timezone.localdate(),
        due_date=quotation.due_date,
        currency=quotation.currency,
        notes=quotation.notes,
        customer_notes=quotation.customer_notes,
        source_document=quotation,
    )

    # نسخ البنود
    for line in quotation.lines.all():
        SalesLine.objects.create(
            document=order,
            product=line.product,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            # لا نمرر line_total، يُحسب تلقائياً في save()
        )

    # إعادة حساب الإجماليات باستخدام منطق الموديل
    order.recompute_totals()

    # نعتبر عرض السعر "مؤكد" بعد التحويل
    quotation.status = SalesDocument.Status.CONFIRMED
    quotation.save(update_fields=["status"])

    return order


# ============================================================
# تحويل طلب بيع → مذكرة تسليم
# ============================================================


@transaction.atomic
def convert_order_to_delivery(order: SalesDocument) -> SalesDocument:
    """
    يحوّل طلب بيع (ORDER) إلى مذكرة تسليم (DELIVERY_NOTE).

    - لو تم التحويل سابقاً يرجّع مذكرة التسليم الموجودة.
    - ينسخ البنود كما هي.
    - يعيد حساب الإجماليات.
    - يحدّث حالة الطلب إلى "تم التسليم".
    """

    if not order.is_order:
        raise ValueError("Sales document is not an order.")

    if not order.can_be_converted_to_delivery():
        raise ValueError("This order cannot be converted to a delivery note.")

    existing_delivery = order.child_documents.filter(
        kind=SalesDocument.Kind.DELIVERY_NOTE
    ).first()
    if existing_delivery:
        return existing_delivery

    delivery = SalesDocument.objects.create(
        kind=SalesDocument.Kind.DELIVERY_NOTE,
        status=SalesDocument.Status.DELIVERED,
        contact=order.contact,
        date=timezone.localdate(),
        due_date=order.due_date,
        currency=order.currency,
        notes=order.notes,
        customer_notes=order.customer_notes,
        source_document=order,
    )

    for line in order.lines.all():
        SalesLine.objects.create(
            document=delivery,
            product=line.product,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            # line_total يتحسب تلقائياً
        )

    # إعادة الحساب من خلال الموديل
    delivery.recompute_totals()

    # نعتبر الطلب "تم تسليمه" بعد إنشاء مذكرة تسليم
    order.status = SalesDocument.Status.DELIVERED
    order.save(update_fields=["status"])

    return delivery


# ============================================================
# تحويل طلب / مذكرة تسليم → فاتورة
# ============================================================


@transaction.atomic
def convert_sales_document_to_invoice(doc: SalesDocument):
    """
    يحوّل طلب بيع أو مذكرة تسليم إلى فاتورة.

    - يحتاج وجود نموذج Invoice في تطبيق accounting.
    - لو وجد InvoiceLine يتم نسخ البنود أيضاً، وإلا تُنشأ فاتورة بدون أسطر.
    - لو تم التحويل سابقاً يرجّع الفاتورة الموجودة.
    """

    if Invoice is None:
        raise RuntimeError("Invoice model not available (accounting app missing).")

    if not doc.can_be_converted_to_invoice():
        raise ValueError("This sales document cannot be converted to an invoice.")

    # لو فيه علاقة صريحة في Invoice مثل: source_sales_document = FK
    existing_invoice = None
    if hasattr(Invoice, "source_sales_document"):
        existing_invoice = (
            Invoice.objects.filter(source_sales_document=doc).first()
        )

    # أو لو فيه OneToOne من ناحية SalesDocument (مثلاً doc.invoice)
    if existing_invoice is None and hasattr(doc, "invoice"):
        existing_invoice = getattr(doc, "invoice", None)

    if existing_invoice:
        return existing_invoice

    # بناء بيانات الفاتورة الأساسية
    invoice_data = {
        "customer": doc.contact,
        "issued_at": timezone.now(),
        "due_date": doc.due_date,
        "currency": getattr(doc, "currency", "OMR"),
        "total_amount": getattr(doc, "total_amount", Decimal("0.000")),
        "total_before_tax": getattr(
            doc, "total_before_tax", getattr(doc, "total_amount", Decimal("0.000"))
        ),
        "total_tax": getattr(doc, "total_tax", Decimal("0.000")),
    }

    # لو في حقل source_sales_document في Invoice نمرّره
    if hasattr(Invoice, "source_sales_document"):
        invoice_data["source_sales_document"] = doc

    invoice = Invoice.objects.create(**invoice_data)

    # لو عندنا InvoiceLine ننسخ البنود
    if InvoiceLine is not None:
        for line in doc.lines.all():
            InvoiceLine.objects.create(
                invoice=invoice,
                product=line.product,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                line_total=line.line_total,
            )

    # تحديث حالة مستند المبيعات
    doc.status = SalesDocument.Status.INVOICED
    doc.save(update_fields=["status"])

    # لو حاب تخزن العكس (مثلاً doc.invoice = invoice)
    # تحتاج حقل FK أو OneToOne في Invoice أو SalesDocument وتضبطه هنا.
    return invoice
