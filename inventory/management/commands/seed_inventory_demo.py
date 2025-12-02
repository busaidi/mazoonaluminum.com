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


class Command(BaseCommand):
    help = "تهيئة بيانات تجريبية للمخزون (تصنيفات، منتجات، مخازن، حركات مخزون)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("🔧 تهيئة بيانات المخزون التجريبية..."))

        # ============================================================
        # 1) وحدات القياس (UoM) - الاعتماد على seed_uom
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
                "رجاءً شغّل أولاً:\n"
                "    python manage.py seed_uom\n"
                "ثم أعد تشغيل:\n"
                "    python manage.py seed_inventory_demo"
            ) from e

        self.stdout.write(self.style.SUCCESS("✓ تم تحميل وحدات القياس (من seed_uom)."))

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
                "pattern": "{prefix}-{year}-{seq:05d}",
                "reset": NumberingScheme.ResetPolicy.YEAR,
                "start": 1,
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ إعدادات المخزون ونظام الترقيم جاهزة."))

        # ============================================================
        # 3) التصنيفات (شجرة ألمنيوم + إكسسوارات)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء تصنيفات المنتجات..."))

        # جذر الألمنيوم
        cat_aluminum, _ = ProductCategory.objects.get_or_create(
            slug="aluminum",
            defaults={
                "name": "aluminum",
                "description": "Aluminum systems and profiles.",
                "is_active": True,
            },
        )

        # تحت الألمنيوم
        cat_mazoon46, _ = ProductCategory.objects.get_or_create(
            slug="mazoon46",
            defaults={
                "name": "mazoon46",
                "description": "Mazoon 46 window/door system.",
                "parent": cat_aluminum,
                "is_active": True,
            },
        )
        if cat_mazoon46.parent_id is None:
            cat_mazoon46.parent = cat_aluminum
            cat_mazoon46.save(update_fields=["parent"])

        cat_mazoon56, _ = ProductCategory.objects.get_or_create(
            slug="mazoon56",
            defaults={
                "name": "mazoon56",
                "description": "Mazoon 56 window/door system.",
                "parent": cat_aluminum,
                "is_active": True,
            },
        )
        if cat_mazoon56.parent_id is None:
            cat_mazoon56.parent = cat_aluminum
            cat_mazoon56.save(update_fields=["parent"])

        cat_napco, _ = ProductCategory.objects.get_or_create(
            slug="napco",
            defaults={
                "name": "napco",
                "description": "Napco aluminum systems.",
                "parent": cat_aluminum,
                "is_active": True,
            },
        )
        if cat_napco.parent_id is None:
            cat_napco.parent = cat_aluminum
            cat_napco.save(update_fields=["parent"])

        cat_napco_45, _ = ProductCategory.objects.get_or_create(
            slug="napco-45system",
            defaults={
                "name": "45system",
                "description": "Napco 45 system.",
                "parent": cat_napco,
                "is_active": True,
            },
        )
        if cat_napco_45.parent_id is None:
            cat_napco_45.parent = cat_napco
            cat_napco_45.save(update_fields=["parent"])

        cat_napco_tb60, _ = ProductCategory.objects.get_or_create(
            slug="napco-tb60",
            defaults={
                "name": "TB60",
                "description": "Napco TB60 system.",
                "parent": cat_napco,
                "is_active": True,
            },
        )
        if cat_napco_tb60.parent_id is None:
            cat_napco_tb60.parent = cat_napco
            cat_napco_tb60.save(update_fields=["parent"])

        # جذر الإكسسوارات
        cat_accessories, _ = ProductCategory.objects.get_or_create(
            slug="accessories",
            defaults={
                "name": "accessories",
                "description": "Accessories like handles, hinges, rubber, corner joints.",
                "is_active": True,
            },
        )

        cat_acc_giesse, _ = ProductCategory.objects.get_or_create(
            slug="acc-giesse",
            defaults={
                "name": "giesse",
                "description": "Giesse hardware.",
                "parent": cat_accessories,
                "is_active": True,
            },
        )
        if cat_acc_giesse.parent_id is None:
            cat_acc_giesse.parent = cat_accessories
            cat_acc_giesse.save(update_fields=["parent"])

        cat_acc_master, _ = ProductCategory.objects.get_or_create(
            slug="acc-master",
            defaults={
                "name": "master",
                "description": "Master hardware.",
                "parent": cat_accessories,
                "is_active": True,
            },
        )
        if cat_acc_master.parent_id is None:
            cat_acc_master.parent = cat_accessories
            cat_acc_master.save(update_fields=["parent"])

        cat_acc_mazoon, _ = ProductCategory.objects.get_or_create(
            slug="acc-mazoon",
            defaults={
                "name": "mazoon",
                "description": "Mazoon accessories.",
                "parent": cat_accessories,
                "is_active": True,
            },
        )
        if cat_acc_mazoon.parent_id is None:
            cat_acc_mazoon.parent = cat_accessories
            cat_acc_mazoon.save(update_fields=["parent"])

        cat_acc_rubber, _ = ProductCategory.objects.get_or_create(
            slug="acc-rubber",
            defaults={
                "name": "rubber",
                "description": "Rubber gaskets and seals.",
                "parent": cat_accessories,
                "is_active": True,
            },
        )
        if cat_acc_rubber.parent_id is None:
            cat_acc_rubber.parent = cat_accessories
            cat_acc_rubber.save(update_fields=["parent"])

        cat_acc_cornerjoint, _ = ProductCategory.objects.get_or_create(
            slug="acc-cornerjoint",
            defaults={
                "name": "cornerjoint",
                "description": "Corner joints for aluminum profiles.",
                "parent": cat_accessories,
                "is_active": True,
            },
        )
        if cat_acc_cornerjoint.parent_id is None:
            cat_acc_cornerjoint.parent = cat_accessories
            cat_acc_cornerjoint.save(update_fields=["parent"])

        self.stdout.write(self.style.SUCCESS("✓ التصنيفات (ألمنيوم + إكسسوارات) جاهزة."))

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

        StockLocation.objects.get_or_create(
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
        # 5) المنتجات (Mazoon 46 + Rubber + مثال مقبض)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("➡ إنشاء منتجات تجريبية مع أسعار..."))

        # 4610 Frame with Architrave
        p_4610, _ = Product.objects.get_or_create(
            code="MZN46-4610",
            defaults={
                "category": cat_mazoon46,
                "name": "4610 Frame with Architrave",
                "short_description": "4610 frame with architrave for Mazoon 46.",
                "description": (
                    "4610 frame profile with architrave for Mazoon 46 system. "
                    "Base UoM is meter, alternative UoM is bar 6.4m."
                ),
                "base_uom": m,
                "alt_uom": bar,
                "alt_factor": Decimal("6.4"),  # 1 BAR = 6.4 M
                "weight_uom": kg,
                "weight_per_base": Decimal("1.234"),
                "default_sale_price": Decimal("3.500"),
                "default_cost_price": Decimal("2.750"),
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        # 4620 Mullion window/door
        p_4620, _ = Product.objects.get_or_create(
            code="MZN46-4620",
            defaults={
                "category": cat_mazoon46,
                "name": "4620 Mullion window/door",
                "short_description": "4620 mullion for Mazoon 46 windows/doors.",
                "description": (
                    "4620 mullion profile for Mazoon 46 window/door system. "
                    "Base UoM is meter, alternative UoM is bar 6.4m."
                ),
                "base_uom": m,
                "alt_uom": bar,
                "alt_factor": Decimal("6.4"),
                "weight_uom": kg,
                "weight_per_base": Decimal("1.234"),
                "default_sale_price": Decimal("3.800"),
                "default_cost_price": Decimal("2.950"),
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        # ربل في كاتيجوري rubber
        rubber_profile, _ = Product.objects.get_or_create(
            code="RUB-MZN-01",
            defaults={
                "category": cat_acc_rubber,
                "name": "Rubber Gasket 120m Roll",
                "short_description": "Rubber gasket sold per meter or roll 120m.",
                "description": (
                    "Standard rubber gasket for Mazoon systems. "
                    "Base UoM is meter, alternative UoM is roll 120m."
                ),
                "base_uom": m,
                "alt_uom": roll,
                "alt_factor": Decimal("120.0"),  # 1 ROLL = 120 M
                "weight_uom": kg,
                "weight_per_base": Decimal("0.050"),
                "default_sale_price": Decimal("0.800"),
                "default_cost_price": Decimal("0.500"),
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        # مثال مقبض في accessories/mazoon (ديمو)
        handle, _ = Product.objects.get_or_create(
            code="ACC-HANDLE-01",
            defaults={
                "category": cat_acc_mazoon,
                "name": "Handle Type 01",
                "short_description": "مقبض نافذة أسود عالي الجودة.",
                "description": "Handle suitable for Mazoon 46 and Mazoon 70 systems.",
                "base_uom": pcs,
                "alt_uom": None,
                "alt_factor": None,
                "weight_uom": kg,
                "weight_per_base": Decimal("0.150"),
                "default_sale_price": Decimal("1.200"),
                "default_cost_price": Decimal("0.800"),
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ المنتجات التجريبية (Mazoon 46 + Rubber) جاهزة."))

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

            # 10 م من 4610 واردة إلى WH-SQ / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=p_4610,
                quantity=Decimal("10.000"),
                uom=m,
                reference="DEMO-IN-4610-001",
                note="رصيد افتتاحي تجريبي لقطاع 4610 في مخزن السويق.",
            )

            # 2 بار 4620 (2 × 6.4 = 12.8 م) واردة إلى WH-SQ / MAIN
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=p_4620,
                quantity=Decimal("2.000"),
                uom=bar,
                reference="DEMO-IN-4620-001",
                note="رصيد افتتاحي تجريبي لباريْن من قطاع 4620.",
            )

            # صرف 5 م من 4610
            create_move_with_line(
                move_type=StockMove.MoveType.OUT,
                from_wh=wh_sq,
                from_loc=loc_sq_main,
                to_wh=None,
                to_loc=None,
                product=p_4610,
                quantity=Decimal("5.000"),
                uom=m,
                reference="DEMO-OUT-4610-001",
                note="صرف تجريبي لقطاع 4610 كطلب عميل.",
            )

            # تحويل 3 م من 4620 إلى مخزن مسقط
            create_move_with_line(
                move_type=StockMove.MoveType.TRANSFER,
                from_wh=wh_sq,
                from_loc=loc_sq_main,
                to_wh=wh_mct,
                to_loc=loc_mct_main,
                product=p_4620,
                quantity=Decimal("3.000"),
                uom=m,
                reference="DEMO-TRF-4620-001",
                note="تحويل تجريبي لكمية من قطاع 4620 إلى مخزن مسقط.",
            )

            # وارد ربل: 1 لفة = 120 متر
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=rubber_profile,
                quantity=Decimal("1.000"),
                uom=roll,
                reference="DEMO-IN-RUB-001",
                note="رصيد افتتاحي تجريبي لفة ربل 120م.",
            )

            # وارد 50 مقبض
            create_move_with_line(
                move_type=StockMove.MoveType.IN,
                from_wh=None,
                from_loc=None,
                to_wh=wh_sq,
                to_loc=loc_sq_main,
                product=handle,
                quantity=Decimal("50.000"),
                uom=pcs,
                reference="DEMO-IN-HND-001",
                note="رصيد افتتاحي تجريبي للمقابض في مخزن السويق.",
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "✓ تم إنشاء الحركات التجريبية، وسيتم تحديث مستويات المخزون عبر خدمة apply_stock_move_status_change."
                )
            )

        self.stdout.write(self.style.SUCCESS("✅ تهيئة بيانات المخزون التجريبية اكتملت بنجاح."))
