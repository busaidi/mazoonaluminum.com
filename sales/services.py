# sales/services.py
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import SalesDocument, SalesLine

try:
    from accounting.models import Invoice
    try:
        from accounting.models import InvoiceLine
    except ImportError:
        InvoiceLine = None
except ImportError:
    Invoice = None
    InvoiceLine = None


@transaction.atomic
def convert_quotation_to_order(quotation: SalesDocument) -> SalesDocument:
    """
    يحوّل عرض سعر واحد إلى طلب بيع جديد.
    """

    if quotation.kind != SalesDocument.Kind.QUOTATION:
        raise ValueError("Document is not a quotation.")

    # لو تم تحويله سابقاً، رجّع نفس الأوردر
    existing_order = quotation.child_documents.filter(
        kind=SalesDocument.Kind.ORDER
    ).first()
    if existing_order:
        return existing_order

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

    for line in quotation.lines.all():
        SalesLine.objects.create(
            document=order,
            product=line.product,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            line_total=line.line_total,
        )

    total_before_tax = order.lines.aggregate(
        s=Sum("line_total")
    )["s"] or Decimal("0.000")
    order.total_before_tax = total_before_tax
    order.total_tax = Decimal("0.000")
    order.total_amount = total_before_tax
    order.save()

    # نعتبر عرض السعر "مؤكد" بعد التحويل
    quotation.status = SalesDocument.Status.CONFIRMED
    quotation.save(update_fields=["status"])

    return order


@transaction.atomic
def convert_order_to_delivery(order: SalesDocument) -> SalesDocument:
    """
    يحوّل طلب بيع إلى مذكرة تسليم.
    """

    if order.kind != SalesDocument.Kind.ORDER:
        raise ValueError("Document is not an order.")

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
            line_total=line.line_total,
        )

    total_before_tax = delivery.lines.aggregate(
        s=Sum("line_total")
    )["s"] or Decimal("0.000")
    delivery.total_before_tax = total_before_tax
    delivery.total_tax = Decimal("0.000")
    delivery.total_amount = total_before_tax
    delivery.save()

    # نعتبر الطلب "تم تسليمه" بعد إنشاء مذكرة تسليم
    order.status = SalesDocument.Status.DELIVERED
    order.save(update_fields=["status"])

    return delivery



@transaction.atomic
def convert_sales_document_to_invoice(doc: SalesDocument):
    """
    يحوّل طلب بيع أو مذكرة تسليم إلى فاتورة.

    - يحتاج وجود نموذج Invoice في تطبيق accounting.
    - لو وجد InvoiceLine يتم نسخ البنود، وإلا تُنشأ فاتورة بدون أسطر.
    """

    if Invoice is None:
        raise RuntimeError("Invoice model not available (accounting app missing).")

    if doc.kind not in (SalesDocument.Kind.ORDER, SalesDocument.Kind.DELIVERY_NOTE):
        raise ValueError("Sales document must be order or delivery note to invoice.")

    # لو فيه فاتورة سابقة تربط بهذا المستند:
    existing_invoice = getattr(doc, "invoice", None)
    if existing_invoice:
        return existing_invoice

    invoice = Invoice.objects.create(
        customer=doc.contact,
        issued_at=timezone.now(),
        due_date=doc.due_date,
        currency=getattr(doc, "currency", "OMR"),
        total_amount=doc.total_amount,
        total_before_tax=getattr(doc, "total_before_tax", doc.total_amount),
        total_tax=getattr(doc, "total_tax", Decimal("0.000")),
        source_sales_document=doc if hasattr(Invoice, "source_sales_document") else None,
    )

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

    # لو حاب تخزن العكس (مثلاً doc.invoice = invoice) تحتاج حقل FK في Invoice أو SalesDocument
    return invoice


