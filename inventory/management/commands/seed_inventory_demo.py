# inventory/management/commands/seed_inventory_demo.py

from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import NumberingScheme
from inventory.models import (
    ProductCategory,
    Product,
    Warehouse,
    StockLocation,
    StockMove,
    StockMoveLine,
    InventorySettings,
)
from uom.models import UnitOfMeasure
from inventory.services import confirm_stock_move  # ✅ استيراد الخدمة لتحديث الأرصدة فعلياً


class Command(BaseCommand):
    help = "تهيئة بيانات تجريبية للمخزون (تصنيفات، منتجات، مخازن، حركات مخزون)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("🔧 تهيئة بيانات المخزون التجريبية..."))

        # ============================================================
        # 1) وحدات القياس (UoM)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ تحميل وحدات القياس الموجودة..."))

        try:
            m = UnitOfMeasure.objects.get(code="M")
            bar = UnitOfMeasure.objects.get(code="BAR")
            roll = UnitOfMeasure.objects.get(code="ROLL")
            pcs = UnitOfMeasure.objects.get(code="PCS")
            kg = UnitOfMeasure.objects.get(code="KG")
        except UnitOfMeasure.DoesNotExist as e:
            raise CommandError(
                "❌ بعض وحدات القياس غير موجودة (M / BAR / ROLL / PCS / KG).\n"
                "رجاءً شغّل أولاً: python manage.py seed_uom"
            ) from e

        self.stdout.write(self.style.SUCCESS("✓ تم تحميل وحدات القياس."))

        # ============================================================
        # 2) إعدادات المخزون + نظام الترقيم
        # ============================================================
        settings = InventorySettings.get_solo()
        if not settings.stock_move_in_prefix: settings.stock_move_in_prefix = "IN"
        if not settings.stock_move_out_prefix: settings.stock_move_out_prefix = "OUT"
        if not settings.stock_move_transfer_prefix: settings.stock_move_transfer_prefix = "TRF"
        settings.save()

        NumberingScheme.objects.get_or_create(
            model_label="inventory.StockMove",
            defaults={
                "field_name": "number",
                "pattern": "{prefix}-{year}-{seq:05d}",
                "reset": NumberingScheme.ResetPolicy.YEAR,
                "start": 1,
                "is_active": True,
            },
        )

        # ============================================================
        # 3) التصنيفات
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء التصنيفات..."))

        # Root
        cat_aluminum, _ = ProductCategory.objects.get_or_create(
            slug="aluminum",
            defaults={"name": "aluminum", "description": "Aluminum systems.", "is_active": True},
        )
        cat_accessories, _ = ProductCategory.objects.get_or_create(
            slug="accessories",
            defaults={"name": "accessories", "description": "Accessories.", "is_active": True},
        )

        # Children (Aluminum)
        def create_cat(slug, name, parent):
            c, _ = ProductCategory.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "parent": parent, "is_active": True}
            )
            if c.parent != parent:  # Ensure parent is set if existed properly
                c.parent = parent
                c.save()
            return c

        cat_mazoon46 = create_cat("mazoon46", "Mazoon 46", cat_aluminum)
        cat_mazoon56 = create_cat("mazoon56", "Mazoon 56", cat_aluminum)
        cat_napco = create_cat("napco", "Napco", cat_aluminum)
        create_cat("napco-45system", "Napco 45", cat_napco)
        create_cat("napco-tb60", "Napco TB60", cat_napco)

        # Children (Accessories)
        cat_acc_mazoon = create_cat("acc-mazoon", "Mazoon Acc", cat_accessories)
        cat_acc_rubber = create_cat("acc-rubber", "Rubber", cat_accessories)
        create_cat("acc-giesse", "Giesse", cat_accessories)
        create_cat("acc-master", "Master", cat_accessories)
        create_cat("acc-cornerjoint", "Corner Joints", cat_accessories)

        # ============================================================
        # 4) المخازن والمواقع
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء المخازن..."))

        wh_sq, _ = Warehouse.objects.get_or_create(
            code="WH-SQ",
            defaults={"name": "مخزن السويق الرئيسي", "is_active": True},
        )
        wh_mct, _ = Warehouse.objects.get_or_create(
            code="WH-MCT",
            defaults={"name": "مخزن مسقط الرئيسي", "is_active": True},
        )

        loc_sq_main, _ = StockLocation.objects.get_or_create(
            warehouse=wh_sq, code="MAIN",
            defaults={"name": "المخزون الرئيسي", "type": StockLocation.LocationType.INTERNAL},
        )
        StockLocation.objects.get_or_create(
            warehouse=wh_sq, code="SCRAP",
            defaults={"name": "منطقة الهالك", "type": StockLocation.LocationType.SCRAP},
        )
        loc_mct_main, _ = StockLocation.objects.get_or_create(
            warehouse=wh_mct, code="MAIN",
            defaults={"name": "المخزون الرئيسي - مسقط", "type": StockLocation.LocationType.INTERNAL},
        )

        # ============================================================
        # 5) المنتجات
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء المنتجات..."))

        # ملاحظة: تم تغيير default_cost_price إلى average_cost ليتوافق مع الموديل
        p_4610, _ = Product.objects.get_or_create(
            code="MZN46-4610",
            defaults={
                "category": cat_mazoon46,
                "name": "4610 Frame with Architrave",
                "base_uom": m,
                "alt_uom": bar,
                "alt_factor": Decimal("6.4"),
                "weight_uom": kg,
                "weight_per_base": Decimal("1.234"),
                "default_sale_price": Decimal("3.500"),
                "average_cost": Decimal("2.750"),  # ✅ Corrected Field Name
                "is_stock_item": True,
                "is_active": True,
            },
        )

        p_4620, _ = Product.objects.get_or_create(
            code="MZN46-4620",
            defaults={
                "category": cat_mazoon46,
                "name": "4620 Mullion window/door",
                "base_uom": m,
                "alt_uom": bar,
                "alt_factor": Decimal("6.4"),
                "weight_uom": kg,
                "weight_per_base": Decimal("1.234"),
                "default_sale_price": Decimal("3.800"),
                "average_cost": Decimal("2.950"),  # ✅ Corrected
                "is_stock_item": True,
                "is_active": True,
            },
        )

        rubber_profile, _ = Product.objects.get_or_create(
            code="RUB-MZN-01",
            defaults={
                "category": cat_acc_rubber,
                "name": "Rubber Gasket 120m Roll",
                "base_uom": m,
                "alt_uom": roll,
                "alt_factor": Decimal("120.0"),
                "weight_uom": kg,
                "weight_per_base": Decimal("0.050"),
                "default_sale_price": Decimal("0.800"),
                "average_cost": Decimal("0.500"),  # ✅ Corrected
                "is_stock_item": True,
                "is_active": True,
            },
        )

        handle, _ = Product.objects.get_or_create(
            code="ACC-HANDLE-01",
            defaults={
                "category": cat_acc_mazoon,
                "name": "Handle Type 01",
                "base_uom": pcs,
                "weight_uom": kg,
                "weight_per_base": Decimal("0.150"),
                "default_sale_price": Decimal("1.200"),
                "average_cost": Decimal("0.800"),  # ✅ Corrected
                "is_stock_item": True,
                "is_active": True,
            },
        )

        # ============================================================
        # 6) حركات مخزون تجريبية
        # ============================================================
        if StockMove.objects.exists():
            self.stdout.write(self.style.WARNING("⚠ حركات المخزون موجودة مسبقاً، تم تخطي الإنشاء."))
        else:
            self.stdout.write(self.style.HTTP_INFO("➡ تنفيذ حركات مخزون وتحديث الأرصدة..."))
            now = timezone.now()

            def create_and_confirm_move(move_type, from_wh, from_loc, to_wh, to_loc, product, qty, uom, ref, note):
                # 1. إنشاء الهيدر
                move = StockMove.objects.create(
                    move_type=move_type,
                    from_warehouse=from_wh, from_location=from_loc,
                    to_warehouse=to_wh, to_location=to_loc,
                    move_date=now,
                    status=StockMove.Status.DRAFT,
                    reference=ref,
                    note=note,
                )

                # 2. إنشاء البند (مع وضع التكلفة لحساب Valuation)
                # نستخدم average_cost الحالي للمنتج كسعر تكلفة للحركة الواردة الافتتاحية
                cost = product.average_cost
                StockMoveLine.objects.create(
                    move=move,
                    product=product,
                    quantity=qty,
                    uom=uom,
                    cost_price=cost  # ✅ Important for valuation
                )

                # 3. تأكيد الحركة وتحديث الأرصدة
                # ✅ استخدام السيرفس الرسمي بدلاً من التحديث اليدوي
                try:
                    confirm_stock_move(move, user=None)
                    self.stdout.write(f"   - تم ترحيل الحركة: {ref}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"   ! خطأ في ترحيل {ref}: {e}"))

            # IN: 4610 -> SQ (10m)
            create_and_confirm_move(
                StockMove.MoveType.IN, None, None, wh_sq, loc_sq_main,
                p_4610, Decimal("10.000"), m, "DEMO-IN-4610", "رصيد افتتاحي"
            )

            # IN: 4620 -> SQ (2 bars)
            create_and_confirm_move(
                StockMove.MoveType.IN, None, None, wh_sq, loc_sq_main,
                p_4620, Decimal("2.000"), bar, "DEMO-IN-4620", "رصيد افتتاحي"
            )

            # OUT: 4610 from SQ (5m)
            create_and_confirm_move(
                StockMove.MoveType.OUT, wh_sq, loc_sq_main, None, None,
                p_4610, Decimal("5.000"), m, "DEMO-OUT-4610", "صرف عميل"
            )

            # TRF: 4620 SQ -> MCT (3m)
            create_and_confirm_move(
                StockMove.MoveType.TRANSFER, wh_sq, loc_sq_main, wh_mct, loc_mct_main,
                p_4620, Decimal("3.000"), m, "DEMO-TRF-4620", "نقل لفرع مسقط"
            )

            # IN: Rubber (1 roll)
            create_and_confirm_move(
                StockMove.MoveType.IN, None, None, wh_sq, loc_sq_main,
                rubber_profile, Decimal("1.000"), roll, "DEMO-IN-RUB", "رصيد افتتاحي"
            )

            # IN: Handle (50 pcs)
            create_and_confirm_move(
                StockMove.MoveType.IN, None, None, wh_sq, loc_sq_main,
                handle, Decimal("50.000"), pcs, "DEMO-IN-HND", "رصيد افتتاحي"
            )

        self.stdout.write(self.style.SUCCESS("✅ تمت تهيئة النظام بنجاح!"))