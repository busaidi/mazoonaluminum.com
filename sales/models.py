# sales/models.py
from decimal import Decimal, InvalidOperation

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from contacts.models import Contact
from inventory.models import Product
from uom.models import UnitOfMeasure

from core.models.base import BaseModel, TimeStampedModel, UserStampedModel
from .managers import (
    SalesDocumentManager,
    SalesLineManager,
    DeliveryNoteManager,
    DeliveryLineManager,
)

# Decimal constants
DECIMAL_ZERO = Decimal("0.000")
DECIMAL_ONE = Decimal("1.000")


# ===================================================================
# Unified Sales Document
# ===================================================================

class SalesDocument(BaseModel):
    """
    Unified sales document:
    - Lifecycle: DRAFT -> SENT -> CONFIRMED (Sales Order) -> [DELIVERY]
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("عرض سعر (مسودة)")
        SENT = "sent", _("عرض سعر (مرسل)")
        CONFIRMED = "confirmed", _("أمر بيع (مؤكد)")
        CANCELLED = "cancelled", _("ملغي")

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", _("قيد الانتظار")
        PARTIAL = "partial", _("تسليم جزئي")
        DELIVERED = "delivered", _("تم التسليم")

    # ========== Core fields ==========

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_("الحالة"),
        db_index=True,
    )

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="sales_documents",
        verbose_name=_("العميل"),
    )

    client_reference = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("مرجع العميل (PO)"),
        help_text=_("رقم الإشارة الخاص بالعميل أو رقم أمر الشراء."),
    )

    date = models.DateField(
        default=timezone.localdate,
        verbose_name=_("التاريخ"),
        db_index=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("تاريخ الانتهاء/الصلاحية"),
    )

    # ========== Addresses ==========

    shipping_address = models.TextField(
        blank=True,
        verbose_name=_("عنوان الشحن"),
    )

    billing_address = models.TextField(
        blank=True,
        verbose_name=_("عنوان الفوترة"),
    )

    # ========== Amounts ==========

    total_before_tax = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الإجمالي قبل الضريبة"),
    )
    total_tax = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("إجمالي الضريبة"),
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
        verbose_name=_("الإجمالي النهائي"),
    )
    currency = models.CharField(
        max_length=3,
        default="OMR",
        verbose_name=_("العملة"),
    )

    # ========== Billing & delivery status ==========

    is_invoiced = models.BooleanField(
        default=False,
        verbose_name=_("مفوتر بالكامل"),
    )

    delivery_status = models.CharField(
        max_length=20,
        default=DeliveryStatus.PENDING,
        choices=DeliveryStatus.choices,
        verbose_name=_("حالة التسليم"),
    )

    # ========== Notes ==========

    notes = models.TextField(blank=True, verbose_name=_("ملاحظات داخلية"))
    customer_notes = models.TextField(blank=True, verbose_name=_("ملاحظات للعميل"))

    objects = SalesDocumentManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مستند مبيعات")
        verbose_name_plural = _("مستندات المبيعات")

    def __str__(self) -> str:
        return f"{self.display_number} - {self.contact}"

    # ========== Validation ==========

    def clean(self):
        """
        Model-level validation.
        - Do not allow cancelling a sales order if there are confirmed deliveries.
        """
        if self.status == self.Status.CANCELLED and self.pk:
            # NOTE: DeliveryNote is defined below in this module.
            has_confirmed_deliveries = self.delivery_notes.filter(
                status=DeliveryNote.Status.CONFIRMED
            ).exists()
            if has_confirmed_deliveries:
                raise ValidationError(
                    _(
                        "لا يمكن إلغاء أمر البيع لأنه يحتوي على عمليات تسليم مؤكدة. "
                        "قم بإلغاء التسليم أولاً."
                    )
                )

    def save(self, *args, **kwargs):
        # Ensure validation logic is applied on direct .save()
        self.clean()
        super().save(*args, **kwargs)

    # ========== Properties ==========

    @property
    def is_quotation(self) -> bool:
        """True while document is still a quotation (not confirmed)."""
        return self.status in [self.Status.DRAFT, self.Status.SENT]

    @property
    def is_order(self) -> bool:
        """True when document is a confirmed sales order."""
        return self.status == self.Status.CONFIRMED

    @property
    def display_number(self) -> str:
        """
        Prefix based on logical type:
        - QN = Quotation
        - SO = Sales Order
        """
        prefix = "QN" if self.is_quotation else "SO"
        if not self.pk:
            return f"{prefix}-NEW"
        return f"{prefix}-{self.pk:04d}"

    def recompute_totals(self, save: bool = True) -> None:
        """
        Recalculate monetary totals based on sales lines.
        """
        agg = self.lines.aggregate(s=models.Sum("line_total"))
        total = agg.get("s") or DECIMAL_ZERO

        self.total_before_tax = total
        self.total_tax = DECIMAL_ZERO  # TODO: add VAT logic later
        self.total_amount = total + self.total_tax

        if save:
            self.save(update_fields=["total_before_tax", "total_tax", "total_amount"])

    def recompute_delivery_status(self, save: bool = True) -> None:
        """
        Compute delivery_status based on confirmed DeliveryLines.
        - PENDING: no confirmed delivered quantity
        - PARTIAL: some, but not all, quantity is delivered
        - DELIVERED: all quantity is delivered
        """
        total_qty = (
            self.lines.aggregate(s=models.Sum("quantity")).get("s") or DECIMAL_ZERO
        )

        # DeliveryLine is defined below in this module.
        delivered_qty = (
            DeliveryLine.objects.filter(
                sales_line__document=self,
                delivery__status=DeliveryNote.Status.CONFIRMED,
            ).aggregate(s=models.Sum("quantity")).get("s")
            or DECIMAL_ZERO
        )

        if total_qty <= DECIMAL_ZERO or delivered_qty <= DECIMAL_ZERO:
            new_status = self.DeliveryStatus.PENDING
        elif delivered_qty < total_qty:
            new_status = self.DeliveryStatus.PARTIAL
        else:
            new_status = self.DeliveryStatus.DELIVERED

        if new_status != self.delivery_status:
            self.delivery_status = new_status
            if save:
                self.save(update_fields=["delivery_status"])


# ===================================================================
# Sales Line
# ===================================================================

class SalesLine(TimeStampedModel, UserStampedModel):
    document = models.ForeignKey(
        SalesDocument,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    description = models.CharField(max_length=255, blank=True)

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ONE,
    )
    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ZERO,
    )
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    line_total = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=DECIMAL_ZERO,
    )

    objects = SalesLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند مبيعات")

    def __str__(self) -> str:
        return f"{self.document.display_number} - {self.product or self.description}"

    # ---------- Validation ----------

    def clean(self):
        """
        Validate a single sales line:
        - quantity > 0
        - unit_price >= 0
        - discount between 0 and 100
        - must have product or description (do not allow fully empty line)
        """
        errors = {}

        if self.quantity is not None and self.quantity <= DECIMAL_ZERO:
            errors["quantity"] = _("الكمية يجب أن تكون أكبر من صفر.")

        if self.unit_price is not None and self.unit_price < DECIMAL_ZERO:
            errors["unit_price"] = _("سعر الوحدة لا يمكن أن يكون سالباً.")

        if self.discount_percent is not None:
            if (
                self.discount_percent < Decimal("0.00")
                or self.discount_percent > Decimal("100.00")
            ):
                errors["discount_percent"] = _(
                    "نسبة الخصم يجب أن تكون بين 0% و 100%."
                )

        if not self.product and not self.description:
            errors["description"] = _(
                "يجب إدخال منتج أو وصف للبند، لا يمكن تركه فارغاً."
            )

        if errors:
            raise ValidationError(errors)

    # ---------- Calculation ----------

    def compute_line_total(self) -> Decimal:
        qty = self.quantity or DECIMAL_ZERO
        price = self.unit_price or DECIMAL_ZERO
        discount = self.discount_percent or DECIMAL_ZERO

        base = qty * price
        if discount > 0:
            base = base * (Decimal("100") - discount) / Decimal("100")

        return base.quantize(Decimal("0.000"))

    @property
    def delivered_quantity(self) -> Decimal:
        """
        Quantity already delivered via confirmed delivery notes.
        """
        total_delivered = (
            self.delivery_lines.filter(
                delivery__status=DeliveryNote.Status.CONFIRMED
            ).aggregate(sum_qty=models.Sum("quantity"))["sum_qty"]
            or DECIMAL_ZERO
        )
        return total_delivered

    @property
    def remaining_quantity(self) -> Decimal:
        """
        Remaining quantity that is still allowed to be delivered.
        Never returns a negative number.
        """
        remaining = (self.quantity or DECIMAL_ZERO) - self.delivered_quantity
        if remaining < DECIMAL_ZERO:
            return DECIMAL_ZERO
        return remaining

    def save(self, *args, **kwargs) -> None:
        """
        - Ensure line_total is always computed from quantity/price/discount.
        - Do NOT persist document totals here to avoid N saves per formset.
          The view should call document.recompute_totals(save=True) once
          after formset.save().
        """
        self.line_total = self.compute_line_total()
        super().save(*args, **kwargs)

        if self.document_id:
            self.document.recompute_totals(save=False)


# ===================================================================
# Delivery Note
# ===================================================================

class DeliveryNote(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودة")
        CONFIRMED = "confirmed", _("مؤكد / تم التسليم")
        CANCELLED = "cancelled", _("ملغي")

    contact = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        null=True,
        blank=True,
    )

    order = models.ForeignKey(
        SalesDocument,
        on_delete=models.PROTECT,
        related_name="delivery_notes",
        limit_choices_to={"status": SalesDocument.Status.CONFIRMED},
        verbose_name=_("أمر البيع"),
        null=True,  # allow direct (standalone) delivery
        blank=True,
    )

    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    notes = models.TextField(blank=True)

    objects = DeliveryNoteManager()

    class Meta:
        ordering = ("-date", "-id")
        verbose_name = _("مذكرة تسليم")

    def __str__(self) -> str:
        return f"{self.display_number}"

    @property
    def display_number(self) -> str:
        return f"DN-{self.pk:04d}" if self.pk else "DN-DRAFT"

    def clean(self):
        """
        Model-level validation for DeliveryNote.
        - Do not confirm a delivery against a cancelled sales order.
        - Require either contact or order.
        """
        errors = {}

        if self.status == self.Status.CONFIRMED and self.order:
            if self.order.status == SalesDocument.Status.CANCELLED:
                errors["order"] = _("لا يمكن تأكيد التسليم لأمر بيع ملغي.")

        if not self.contact and not self.order:
            errors["contact"] = _(
                "يجب تحديد عميل مباشرة أو ربط مذكرة التسليم بأمر بيع."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        - Auto-fill contact from order if missing.
        - Recompute delivery_status on related sales document when status changes.
        """
        # Keep previous status to detect changes (for existing notes)
        previous_status = None
        if self.pk:
            try:
                previous_status = DeliveryNote.objects.get(pk=self.pk).status
            except DeliveryNote.DoesNotExist:
                previous_status = None

        # If order is set and contact is empty, copy contact from order
        if self.order and not self.contact:
            self.contact = self.order.contact

        self.clean()
        super().save(*args, **kwargs)

        # If linked to an order and status changed, recompute delivery status
        if self.order_id and previous_status != self.status:
            self.order.recompute_delivery_status(save=True)


# ===================================================================
# Delivery Line
# ===================================================================

class DeliveryLine(TimeStampedModel, UserStampedModel):
    delivery = models.ForeignKey(
        DeliveryNote,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    sales_line = models.ForeignKey(
        SalesLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_lines",
        verbose_name=_("بند الطلب"),
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    description = models.CharField(max_length=255, blank=True)
    uom = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=DECIMAL_ONE,
    )

    objects = DeliveryLineManager()

    class Meta:
        ordering = ("id",)
        verbose_name = _("بند تسليم")

    def __str__(self) -> str:
        return f"{self.delivery.display_number} - {self.product or self.description}"

    def clean(self):
        """
        Validate delivery line:
        - quantity > 0
        - If linked to a sales_line & order, they must match.
        - If delivery is CONFIRMED: do not exceed remaining sales quantity
          (taking into account edits to existing confirmed lines).
        """
        errors = {}

        # 1) Basic quantity validation
        if self.quantity is not None and self.quantity <= DECIMAL_ZERO:
            errors["quantity"] = _("كمية التسليم يجب أن تكون أكبر من صفر.")

        # 2) Ensure sales_line belongs to the same order linked to this delivery
        if self.sales_line and self.delivery and self.delivery.order:
            if self.sales_line.document_id != self.delivery.order_id:
                errors["sales_line"] = _(
                    "بند الطلب المحدد لا ينتمي لأمر البيع المرتبط بمذكرة التسليم."
                )

        # 3) Over-delivery protection (only when the note is CONFIRMED)
        if (
            self.sales_line
            and self.delivery
            and self.delivery.status == DeliveryNote.Status.CONFIRMED
        ):
            # Remaining quantity on the sales line (based on other confirmed deliveries)
            remaining = self.sales_line.remaining_quantity

            # If we are editing an existing line, we should "return" the old quantity
            # to the remaining balance before comparing with the new quantity.
            if self.pk:
                try:
                    original_line = type(self).objects.get(pk=self.pk)
                except type(self).DoesNotExist:
                    original_line = None

                if (
                    original_line
                    and original_line.delivery
                    and original_line.delivery.status == DeliveryNote.Status.CONFIRMED
                    and original_line.quantity is not None
                ):
                    # Add back the original quantity to the remaining amount
                    remaining += original_line.quantity

            if self.quantity and self.quantity > remaining:
                errors["quantity"] = _(
                    "كمية التسليم تتجاوز الكمية المتبقية في أمر البيع. "
                    f"المتاح حالياً: {remaining}"
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        - Auto-populate product & UOM from the related sales_line if not set.
        - After saving, recompute delivery_status on the related SalesDocument.
        """
        # Auto-fill from sales_line if provided
        if self.sales_line:
            if not self.product:
                self.product = self.sales_line.product
            if not self.uom:
                self.uom = self.sales_line.uom
            if not self.description and self.sales_line.description:
                self.description = self.sales_line.description

        self.clean()
        super().save(*args, **kwargs)

        # Update delivery status on related sales document
        if self.sales_line and self.sales_line.document_id:
            self.sales_line.document.recompute_delivery_status(save=True)
