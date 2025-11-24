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
    InventorySettings,
)
from uom.models import UnitOfMeasure


class Command(BaseCommand):
    help = "Seed demo data for inventory (UoM, categories, products, warehouses, stock moves)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding inventory demo data..."))

        # ============================================================
        # 1) وحدات القياس (UoM)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("Creating units of measure..."))

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

        self.stdout.write(self.style.SUCCESS("✓ Units of measure ready."))

        # ============================================================
        # 2) إعدادات المخزون (InventorySettings + NumberingScheme)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("Ensuring inventory settings & numbering scheme..."))

        settings = InventorySettings.get_solo()
        if not settings.stock_move_in_prefix:
            settings.stock_move_in_prefix = "IN"
        if not settings.stock_move_out_prefix:
            settings.stock_move_out_prefix = "OUT"
        if not settings.stock_move_transfer_prefix:
            settings.stock_move_transfer_prefix = "TRF"
        settings.save()

        # Numbering scheme for StockMove
        NumberingScheme.objects.get_or_create(
            model_label="inventory.StockMove",
            defaults={
                "field_name": "number",
                # نستخدم {prefix} من get_numbering_context على StockMove
                "pattern": "{prefix}-{year}-{seq:05d}",
                "reset": NumberingScheme.ResetPolicy.YEAR,
                "start": 1,
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ InventorySettings & StockMove numbering scheme ready."))

        # ============================================================
        # 3) التصنيفات (Categories)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("Creating product categories..."))

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
                "name": "إكسسوارات",
                "description": "إكسسوارات الألمنيوم مثل المقابض والمفصلات.",
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

        self.stdout.write(self.style.SUCCESS("✓ Categories ready."))

        # ============================================================
        # 4) المخازن والمواقع (Warehouses & Locations)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("Creating warehouses & locations..."))

        wh_sq, _ = Warehouse.objects.get_or_create(
            code="WH-SQ",
            defaults={
                "name": "Warehouse Al Suwaiq",
                "description": "المخزن الرئيسي في السويق.",
                "is_active": True,
            },
        )

        wh_mct, _ = Warehouse.objects.get_or_create(
            code="WH-MCT",
            defaults={
                "name": "Warehouse Muscat",
                "description": "مخزن مسقط الرئيسي.",
                "is_active": True,
            },
        )

        # مواقع داخل السويق
        loc_sq_main, _ = StockLocation.objects.get_or_create(
            warehouse=wh_sq,
            code="MAIN",
            defaults={
                "name": "Main stock",
                "type": StockLocation.LocationType.INTERNAL,
                "is_active": True,
            },
        )

        loc_sq_scrap, _ = StockLocation.objects.get_or_create(
            warehouse=wh_sq,
            code="SCRAP",
            defaults={
                "name": "Scrap area",
                "type": StockLocation.LocationType.SCRAP,
                "is_active": True,
            },
        )

        # مواقع داخل مسقط
        loc_mct_main, _ = StockLocation.objects.get_or_create(
            warehouse=wh_mct,
            code="MAIN",
            defaults={
                "name": "Main stock",
                "type": StockLocation.LocationType.INTERNAL,
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ Warehouses & locations ready."))

        # ============================================================
        # 5) المنتجات (Products)
        # ============================================================
        self.stdout.write(self.style.HTTP_INFO("Creating products..."))

        # مثال: قطاع إطار نافذة بطول بالمتر، حزمة = 6.4 متر
        frame, _ = Product.objects.get_or_create(
            code="MZN-46-FRAME",
            defaults={
                "category": cat_systems,
                "name": "Mazoon 46 Frame",
                "short_description": "قطاع إطار نظام Mazoon 46.",
                "description": "قطاع إطار أساسي للنوافذ، يستخدم كوحدة قياس بالمتر مع حزمة 6.4 متر.",
                "base_uom": m,
                "alt_uom": bundle,
                "alt_factor": Decimal("6.4"),  # 1 BUNDLE = 6.4 M
                "weight_uom": kg,
                "weight_per_base": Decimal("1.85"),  # 1.85 كجم لكل متر كمثال
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
                "short_description": "مقبض نافذة أسود.",
                "description": "مقبض عالي الجودة مناسب لأنظمة Mazoon 46 و 70.",
                "base_uom": pcs,
                "alt_uom": None,
                "alt_factor": None,
                "weight_uom": kg,
                "weight_per_base": Decimal("0.15"),  # 150 جم لكل مقبض
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
                "short_description": "زجاج شفاف 6 مم.",
                "description": "لوح زجاج شفاف بسماكة 6 مم.",
                "base_uom": m,
                "alt_uom": None,
                "alt_factor": None,
                "weight_uom": kg,
                "weight_per_base": Decimal("15.0"),  # مثال تقريبي
                "is_stock_item": True,
                "is_active": True,
                "is_published": False,
            },
        )

        self.stdout.write(self.style.SUCCESS("✓ Products ready."))

        # ============================================================
        # 6) حركات مخزون تجريبية (StockMoves → StockLevels)
        # ============================================================
        if StockMove.objects.exists():
            self.stdout.write(
                self.style.WARNING(
                    "StockMove table is not empty; skipping demo moves to avoid duplicates."
                )
            )
        else:
            self.stdout.write(self.style.HTTP_INFO("Creating demo stock moves (IN / OUT / TRANSFER)..."))

            now = timezone.now()

            # 10 متر FRAME واردة إلى WH-SQ / MAIN
            StockMove.objects.create(
                product=frame,
                move_type=StockMove.MoveType.IN,
                from_warehouse=None,
                from_location=None,
                to_warehouse=wh_sq,
                to_location=loc_sq_main,
                quantity=Decimal("10.000"),
                uom=m,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-IN-001",
                note="Initial stock for frame in Suwaiq.",
            )

            # 2 حزم FRAME (2 * 6.4 = 12.8 متر) واردة إلى WH-SQ / MAIN
            StockMove.objects.create(
                product=frame,
                move_type=StockMove.MoveType.IN,
                from_warehouse=None,
                from_location=None,
                to_warehouse=wh_sq,
                to_location=loc_sq_main,
                quantity=Decimal("2.000"),
                uom=bundle,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-IN-002",
                note="Two bundles of frame (2 * 6.4m).",
            )

            # 5 متر FRAME صادرة من WH-SQ / MAIN (طلب عميل مثلاً)
            StockMove.objects.create(
                product=frame,
                move_type=StockMove.MoveType.OUT,
                from_warehouse=wh_sq,
                from_location=loc_sq_main,
                to_warehouse=None,
                to_location=None,
                quantity=Decimal("5.000"),
                uom=m,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-OUT-001",
                note="Customer order demo.",
            )

            # 3 متر FRAME محوّلة من WH-SQ / MAIN إلى WH-MCT / MAIN
            StockMove.objects.create(
                product=frame,
                move_type=StockMove.MoveType.TRANSFER,
                from_warehouse=wh_sq,
                from_location=loc_sq_main,
                to_warehouse=wh_mct,
                to_location=loc_mct_main,
                quantity=Decimal("3.000"),
                uom=m,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-TRF-001",
                note="Transfer some frame to Muscat warehouse.",
            )

            # 50 مقبض وارد إلى WH-SQ / MAIN
            StockMove.objects.create(
                product=handle,
                move_type=StockMove.MoveType.IN,
                from_warehouse=None,
                from_location=None,
                to_warehouse=wh_sq,
                to_location=loc_sq_main,
                quantity=Decimal("50.000"),
                uom=pcs,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-IN-003",
                note="Initial stock for handles.",
            )

            # 20 مقبض صادرة من WH-SQ / MAIN
            StockMove.objects.create(
                product=handle,
                move_type=StockMove.MoveType.OUT,
                from_warehouse=wh_sq,
                from_location=loc_sq_main,
                to_warehouse=None,
                to_location=None,
                quantity=Decimal("20.000"),
                uom=pcs,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-OUT-002",
                note="Handle demo issue.",
            )

            # زجاج وارد لمسقط
            StockMove.objects.create(
                product=glass_clear,
                move_type=StockMove.MoveType.IN,
                from_warehouse=None,
                from_location=None,
                to_warehouse=wh_mct,
                to_location=loc_mct_main,
                quantity=Decimal("15.000"),
                uom=m,
                status=StockMove.Status.DONE,
                move_date=now,
                reference="DEMO-IN-004",
                note="Initial glass stock in Muscat.",
            )

            self.stdout.write(self.style.SUCCESS("✓ Demo stock moves created (StockLevels updated via service)."))

        self.stdout.write(self.style.SUCCESS("✅ Inventory demo seed completed successfully."))
