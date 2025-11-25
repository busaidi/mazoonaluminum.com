# inventory/management/commands/seed_inventory_demo.py

from decimal import Decimal

from django.core.management.base import BaseCommand
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


class Command(BaseCommand):
    help = "تهيئة بيانات تجريبية للمخزون (وحدات قياس، تصنيفات، منتجات، مخازن، حركات مخزون)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("🔧 تهيئة بيانات المخزون التجريبية..."))

        # ============================================================
        # 1) وحدات القياس (UoM)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء وحدات القياس..."))

        m, _ = UnitOfMeasure.objects.get_or_create(
            code="M",
            defaults={
                "name_ar": "متر",
                "name_en": "Meter",
                "symbol": "m",
                "is_active": True,
            },
        )

        bundle, _ = UnitOfMeasure.objects.get_or_create(
            code="BUNDLE",
            defaults={
                "name_ar": "حزمة (بار 6.4م)",
                "name_en": "Bundle (bar 6.4m)",
                "symbol": "B",
                "is_active": True,
            },
        )

        pcs, _ = UnitOfMeasure.objects.get_or_create(
            code="PCS",
            defaults={
                "name_ar": "قطعة",
                "name_en": "Piece",
                "symbol": "pcs",
                "is_active": True,
            },
        )

        kg, _ = UnitOfMeasure.objects.get_or_create(
            code="KG",
            defaults={
                "name_ar": "كيلوجرام",
                "name_en": "Kilogram",
                "symbol": "kg",
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ وحدات القياس جاهزة."))

        # ============================================================
        # 2) إعدادات المخزون + نظام الترقيم
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ التأكد من إعدادات المخزون ونظام الترقيم..."))

        settings = InventorySettings.get_solo()
        if not settings.stock_move_in_prefix:
            settings.stock_move_in_prefix = "IN"
        if not settings.stock_move_out_prefix:
            settings.stock_move_out_prefix = "OUT"
        if not settings.stock_move_transfer_prefix:
            settings.stock_move_transfer_prefix = "TRF"
        settings.save()

        NumberingScheme.objects.get_or_create(
            model_label="inventory.StockMove",
            defaults={
                "field_name": "number",
                "pattern": "{prefix}-{year}-{seq:05d}",  # يستخدم {prefix} من StockMove.get_numbering_context
                "reset": NumberingScheme.ResetPolicy.YEAR,
                "start": 1,
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ إعدادات المخزون ونظام الترقيم جاهزة."))

        # ============================================================
        # 3) التصنيفات
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء تصنيفات المنتجات..."))

        cat_systems, _ = ProductCategory.objects.get_or_create(
            slug="aluminum-systems",
            defaults={
                "name": "أنظمة الألمنيوم",
                "description": "أنظمة نوافذ وأبواب Mazoon عالية الجودة.",
                "is_active": True,
            },
        )

        cat_accessories, _ = ProductCategory.objects.get_or_create(
            slug="accessories",
            defaults={
                "name": "إكسسوارات الألمنيوم",
                "description": "إكسسوارات مثل المقابض والمفصلات والمسامير.",
                "is_active": True,
            },
        )

        cat_glass, _ = ProductCategory.objects.get_or_create(
            slug="glass",
            defaults={
                "name": "الزجاج",
                "description": "أنواع مختلفة من الزجاج المستخدم في الأنظمة.",
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ التصنيفات جاهزة."))

        # ============================================================
        # 4) المخازن والمواقع
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء المخازن والمواقع..."))

        wh_sq, _ = Warehouse.objects.get_or_create(
            code="WH-SQ",
            defaults={
                "name": "مخزن السويق الرئيسي",
                "description": "المخزن الرئيسي في ولاية السويق.",
                "is_active": True,
            },
        )

        wh_mct, _ = Warehouse.objects.get_or_create(
            code="WH-MCT",
            defaults={
                "name": "مخزن مسقط الرئيسي",
                "description": "مخزن رئيسي لتجهيز الطلبات في مسقط.",
                "is_active": True,
            },
        )

        # مواقع داخل السويق
        loc_sq_main, _ = StockLocation.objects.get_or_create(
            warehouse=wh_sq,
            code="MAIN",
            defaults={
                "name": "المخزون الرئيسي",
                "type": StockLocation.LocationType.INTERNAL,
                "is_active": True,
            },
        )

        loc_sq_scrap, _ = StockLocation.objects.get_or_create(
            warehouse=wh_sq,
            code="SCRAP",
            defaults={
                "name": "منطقة الهالك",
                "type": StockLocation.LocationType.SCRAP,
                "is_active": True,
            },
        )

        # مواقع داخل مسقط
        loc_mct_main, _ = StockLocation.objects.get_or_create(
            warehouse=wh_mct,
            code="MAIN",
            defaults={
                "name": "المخزون الرئيسي - مسقط",
                "type": StockLocation.LocationType.INTERNAL,
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ المخازن والمواقع جاهزة."))

        # ============================================================
        # 5) المنتجات (مع أسعار البيع والتكلفة)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء منتجات تجريبية مع أسعار..."))

        frame, _ = Product.objects.get_or_create(
            code="MZN-46-FRAME",
            defaults={
                "category": cat_systems,
                "name": "Mazoon 46 Frame",
                "short_description": "قطاع إطار نظام Mazoon 46.",
                "description": "قطاع إطار أساسي لنظام نوافذ Mazoon 46، يُباع بالمتر مع إمكانية البيع على شكل حزم بطول 6.4 متر.",
                "base_uom": m,
                "alt_uom": bundle,
                "alt_factor": Decimal("6.4"),  # 1 BUNDLE = 6.4 M
                "weight_uom": kg,
                "weight_per_base": Decimal("1.85"),  # مثال: 1.85 كجم لكل متر
                "default_sale_price": Decimal("3.500"),  # سعر البيع لكل متر
                "default_cost_price": Decimal("2.750"),  # تكلفة تقديرية لكل متر
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        handle, _ = Product.objects.get_or_create(
            code="ACC-HANDLE-01",
            defaults={
                "category": cat_accessories,
                "name": "Handle Type 01",
                "short_description": "مقبض نافذة أسود عالي الجودة.",
                "description": "مقبض أنيق وقوي مناسب لأنظمة Mazoon 46 و Mazoon 70، تشطيب أسود مطفي.",
                "base_uom": pcs,
                "alt_uom": None,
                "alt_factor": None,
                "weight_uom": kg,
                "weight_per_base": Decimal("0.15"),  # 150 جم لكل مقبض
                "default_sale_price": Decimal("1.200"),  # سعر بيع للمقبض
                "default_cost_price": Decimal("0.800"),  # تكلفة تقريبية للمقبض
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        glass_clear, _ = Product.objects.get_or_create(
            code="GLS-6-CL",
            defaults={
                "category": cat_glass,
                "name": "Clear Glass 6mm",
                "short_description": "زجاج شفاف سماكة 6 مم.",
                "description": "لوح زجاج شفاف سماكة 6 مم للاستخدام في النوافذ والأبواب الزجاجية.",
                "base_uom": m,
                "alt_uom": None,
                "alt_factor": None,
                "weight_uom": kg,
                "weight_per_base": Decimal("15.0"),  # مثال تقريبي
                "default_sale_price": Decimal("20.000"),  # سعر بيع للمتر المربع مثلاً
                "default_cost_price": Decimal("15.000"),  # تكلفة تقريبية
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ المنتجات التجريبية (مع الأسعار) جاهزة."))

        # ============================================================
        # 6) حركات مخزون تجريبية (StockMove + StockMoveLine)
        # ============================================================
        if StockMove.objects.exists():
            self.stdout.write(
                self.style.WARNING(
                    "⚠ جدول حركات المخزون (StockMove) غير فارغ؛ سيتم تجاوز إنشاء الحركات التجريبية لتفادي التكرار."
                )
            )
        else:
            self.stdout.write(self.style.HTTP_INFO("➡ إنشاء حركات مخزون تجريبية (وارد / صادر / تحويل)..."))

            now = timezone.now()

            def create_move_with_line(
                *,
                move_type,
                from_wh,
                from_loc,
                to_wh,
                to_loc,
                product,
                quantity: Decimal,
                uom,
                reference: str,
                note: str,
            ):
                """
                Helper:
                  1) ينشئ StockMove في حالة DRAFT
                  2) يضيف سطر واحد StockMoveLine
                  3) يغيّر الحالة إلى DONE ويعمل save()
                     → هذا يشغّل apply_stock_move_status_change ويحدّث StockLevel
                """
                move = StockMove.objects.create(
                    move_type=move_type,
                    from_warehouse=from_wh,
                    from_location=from_loc,
                    to_warehouse=to_wh,
                    to_location=to_loc,
                    move_date=now,
                    status=StockMove.Status.DRAFT,
                    reference=reference,
                    note=note,
                )

                StockMoveLine.objects.create(
                    move=move,
                    product=product,
                    quantity=quantity,
                    uom=uom,
                )

                move.status = StockMove.Status.DONE
                move.save()
                return move

            # 10 متر FRAME واردة إلى WH-SQ / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=frame,
                quantity=Decimal("10.000"),
                uom=m,
                reference="DEMO-IN-001",
                note="رصيد افتتاحي تجريبي لقطاع الإطار في مخزن السويق.",
            )

            # 2 حزم FRAME (2 × 6.4 = 12.8 متر) واردة إلى WH-SQ / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=frame,
                quantity=Decimal("2.000"),
                uom=bundle,
                reference="DEMO-IN-002",
                note="رصيد افتتاحي تجريبي لحزمتين من قطاع الإطار (2 × 6.4م).",
            )

            # 5 متر FRAME صادرة من WH-SQ / MAIN (طلب عميل)
            create_move_with_line(
                move_type=StockMove.MoveType.OUT,
                from_wh=wh_sq,
                from_loc=loc_sq_main,
                to_wh=None,
                to_loc=None,
                product=frame,
                quantity=Decimal("5.000"),
                uom=m,
                reference="DEMO-OUT-001",
                note="صرف تجريبي لقطاع الإطار كطلب عميل.",
            )

            # 3 متر FRAME تحويل من WH-SQ / MAIN إلى WH-MCT / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.TRANSFER,
                from_wh=wh_sq,
                from_loc=loc_sq_main,
                to_wh=wh_mct,
                to_loc=loc_mct_main,
                product=frame,
                quantity=Decimal("3.000"),
                uom=m,
                reference="DEMO-TRF-001",
                note="تحويل تجريبي لكمية من قطاع الإطار إلى مخزن مسقط.",
            )

            # 50 مقبض وارد إلى WH-SQ / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=handle,
                quantity=Decimal("50.000"),
                uom=pcs,
                reference="DEMO-IN-003",
                note="رصيد افتتاحي تجريبي للمقابض في مخزن السويق.",
            )

            # 20 مقبض صادرة من WH-SQ / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.OUT,
                from_wh=wh_sq,
                from_loc=loc_sq_main,
                to_wh=None,
                to_loc=None,
                product=handle,
                quantity=Decimal("20.000"),
                uom=pcs,
                reference="DEMO-OUT-002",
                note="صرف تجريبي لعدد من المقابض.",
            )

            # زجاج وارد لمسقط
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_mct,
                to_loc=loc_mct_main,
                product=glass_clear,
                quantity=Decimal("15.000"),
                uom=m,
                reference="DEMO-IN-004",
                note="رصيد افتتاحي تجريبي للزجاج في مخزن مسقط.",
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "✓ تم إنشاء الحركات التجريبية، وسيتم تحديث مستويات المخزون عبر خدمة apply_stock_move_status_change."
                )
            )

        self.stdout.write(self.style.SUCCESS("✅ تهيئة بيانات المخزون التجريبية اكتملت بنجاح."))
