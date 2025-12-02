from django.core.management.base import BaseCommand
from django.db import transaction

from uom.models import UomCategory, UnitOfMeasure


class Command(BaseCommand):
    help = "Seed default unit of measure categories and units."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding UoM categories and units..."))

        # ============================
        # 1) Seed categories
        # ============================
        categories_data = [
            {
                "code": "length",
                "name_ar": "الطول",
                "name_en": "Length",
                "description": "وحدات قياس الأطوال مثل المتر والمليمتر.",
            },
            {
                "code": "weight",
                "name_ar": "الوزن",
                "name_en": "Weight",
                "description": "وحدات قياس الأوزان مثل الكيلوجرام والطن.",
            },
            {
                "code": "piece",
                "name_ar": "العدد / القطعة",
                "name_en": "Piece / Unit",
                "description": "وحدات عددية مثل قطعة، مجموعة، لفة، حزمة، كرتون.",
            },
            {
                "code": "area",
                "name_ar": "المساحة",
                "name_en": "Area",
                "description": "وحدات مساحة مثل المتر المربع.",
            },
            {
                "code": "volume",
                "name_ar": "الحجم",
                "name_en": "Volume",
                "description": "وحدات حجم مثل المتر المكعب واللتر.",
            },
            {
                "code": "time",
                "name_ar": "الوقت",
                "name_en": "Time",
                "description": "وحدات زمنية مثل الساعة واليوم.",
            },
        ]

        categories = {}

        for data in categories_data:
            obj, created = UomCategory.objects.update_or_create(
                code=data["code"],
                defaults={
                    "name_ar": data["name_ar"],
                    "name_en": data["name_en"],
                    "description": data.get("description", ""),
                    "is_active": True,
                },
            )
            categories[data["code"]] = obj
            if created:
                self.stdout.write(self.style.SUCCESS(f"  [OK] Created category: {obj.code}"))
            else:
                self.stdout.write(self.style.WARNING(f"  [..] Updated category: {obj.code}"))

        # ============================
        # 2) Seed units
        # ============================
        units_data = [
            # ---- Length ----
            {
                "category": "length",
                "code": "M",
                "name_ar": "متر",
                "name_en": "Meter",
                "symbol": "م",
                "notes": "الوحدة الأساسية في الألمنيوم (طول).",
            },
            {
                "category": "length",
                "code": "MM",
                "name_ar": "مليمتر",
                "name_en": "Millimeter",
                "symbol": "مم",
                "notes": "",
            },
            {
                "category": "length",
                "code": "CM",
                "name_ar": "سنتيمتر",
                "name_en": "Centimeter",
                "symbol": "سم",
                "notes": "",
            },

            # ---- Weight ----
            {
                "category": "weight",
                "code": "KG",
                "name_ar": "كيلوجرام",
                "name_en": "Kilogram",
                "symbol": "كجم",
                "notes": "الوحدة الأساسية للأوزان.",
            },
            {
                "category": "weight",
                "code": "G",
                "name_ar": "جرام",
                "name_en": "Gram",
                "symbol": "جم",
                "notes": "",
            },
            {
                "category": "weight",
                "code": "TON",
                "name_ar": "طن",
                "name_en": "Ton",
                "symbol": "طن",
                "notes": "",
            },

            # ---- Piece / unit ----
            {
                "category": "piece",
                "code": "PCS",
                "name_ar": "قطعة",
                "name_en": "Piece",
                "symbol": "pcs",
                "notes": "قطعة واحدة (مقابض، مفصلات، ...).",
            },
            {
                "category": "piece",
                "code": "SET",
                "name_ar": "طقم",
                "name_en": "Set",
                "symbol": "set",
                "notes": "مجموعة قطع معًا (طقم كامل).",
            },
            {
                "category": "piece",
                "code": "ROLL",
                "name_ar": "لفة",
                "name_en": "Roll",
                "symbol": "roll",
                "notes": "تُستخدم لوحدات اللفة (جوانات، ربل...). الطول الفعلي يحدد في المنتج (alt_factor).",
            },
            {
                "category": "piece",
                "code": "BUNDLE",
                "name_ar": "حزمة",
                "name_en": "Bundle",
                "symbol": "bundle",
                "notes": "مجموعة قطع أو بارات مجمعة معًا. الطول أو العدد يحدد في المنتج.",
            },
            {
                "category": "piece",
                "code": "BAR",
                "name_ar": "بار",
                "name_en": "Bar",
                "symbol": "bar",
                "notes": "قضيب/بار ألمنيوم (مثلاً 6.4 م). الطول الفعلي يحدد في المنتج (alt_factor).",
            },
            {
                "category": "piece",
                "code": "BOX",
                "name_ar": "كرتون",
                "name_en": "Box / Carton",
                "symbol": "box",
                "notes": "",
            },

            # ---- Area ----
            {
                "category": "area",
                "code": "M2",
                "name_ar": "متر مربع",
                "name_en": "Square meter",
                "symbol": "م²",
                "notes": "لواجهات وزجاج ومساحات.",
            },

            # ---- Volume ----
            {
                "category": "volume",
                "code": "M3",
                "name_ar": "متر مكعب",
                "name_en": "Cubic meter",
                "symbol": "م³",
                "notes": "",
            },
            {
                "category": "volume",
                "code": "L",
                "name_ar": "لتر",
                "name_en": "Liter",
                "symbol": "L",
                "notes": "",
            },

            # ---- Time ----
            {
                "category": "time",
                "code": "HOUR",
                "name_ar": "ساعة",
                "name_en": "Hour",
                "symbol": "h",
                "notes": "تُستخدم في الخدمات، الأجر بالساعة.",
            },
            {
                "category": "time",
                "code": "DAY",
                "name_ar": "يوم",
                "name_en": "Day",
                "symbol": "d",
                "notes": "",
            },
        ]

        for data in units_data:
            category_code = data["category"]
            category = categories.get(category_code)

            if not category:
                self.stdout.write(
                    self.style.ERROR(f"  [ERR] Category '{category_code}' not found for unit {data['code']}"),
                )
                continue

            obj, created = UnitOfMeasure.objects.update_or_create(
                code=data["code"],
                defaults={
                    "category": category,
                    "name_ar": data["name_ar"],
                    "name_en": data["name_en"],
                    "symbol": data.get("symbol", ""),
                    "is_active": True,
                    "notes": data.get("notes", ""),
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"  [OK] Created unit: {obj.code}"))
            else:
                self.stdout.write(self.style.WARNING(f"  [..] Updated unit: {obj.code}"))

        self.stdout.write(self.style.SUCCESS("Done seeding UoM categories and units."))
