from django.core.management.base import BaseCommand
from website.models import Category, Tag, BlogPost, Product
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed default categories, tags, blog posts, and product for Mazoon Aluminum website (AR + EN)."

    def handle(self, *args, **options):

        # -------------------------
        # CATEGORIES (AR + EN)
        # -------------------------
        categories_data = [
            # slug, name_ar, name_en
            ("aluminum-systems", "أنظمة الألمنيوم", "Aluminum systems"),
            ("product", "المنتجات", "Products"),
            ("news", "الأخبار", "News"),
            ("technology", "التقنيات", "Technology"),
            ("mazoon-blog", "مدونة مزون", "Mazoon blog"),
        ]

        categories = []
        for slug, name_ar, name_en in categories_data:
            cat, _ = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    "name_ar": name_ar,
                    "name_en": name_en,
                },
            )
            # لو موجود قديم بدون انجليزي نحدّثه
            updated = False
            if not cat.name_en:
                cat.name_en = name_en
                updated = True
            if updated:
                cat.save()
            categories.append(cat)

        self.stdout.write(self.style.SUCCESS(f"Created/updated {len(categories)} categories."))

        # -------------------------
        # TAGS (AR + EN)
        # -------------------------
        tags_data = [
            # slug, name_ar, name_en
            ("hinged-system", "نظام مفصلي", "Hinged system"),
            ("sliding-system", "نظام سحب", "Sliding system"),
            ("thermal-break", "عزل حراري", "Thermal break"),
            ("facades", "واجهات", "Facades"),
            ("projects", "مشاريع", "Projects"),
        ]

        tags = []
        for slug, name_ar, name_en in tags_data:
            tag, _ = Tag.objects.get_or_create(
                slug=slug,
                defaults={
                    "name_ar": name_ar,
                    "name_en": name_en,
                },
            )
            updated = False
            if not tag.name_en:
                tag.name_en = name_en
                updated = True
            if updated:
                tag.save()
            tags.append(tag)

        self.stdout.write(self.style.SUCCESS(f"Created/updated {len(tags)} tags."))

        # -------------------------
        # PRODUCTS (AR + EN)
        # -------------------------
        products_data = [
            # name_ar, name_en, slug, desc_ar, desc_en
            (
                "مزون 45",
                "Mazoon 45",
                "mazoon-45",
                "نظام مفصلي بسيط وسهل التصنيع، مناسب للنوافذ والأبواب القياسية.",
                "A simple hinged system that is easy to fabricate, suitable for standard windows and doors.",
            ),
            (
                "مزون 46",
                "Mazoon 46",
                "mazoon-46",
                "تطوير لنظام مزون 45 مع غرف عزل إضافية وتحسين في الأداء.",
                "An improved version of Mazoon 45 with extra chambers and better performance.",
            ),
            (
                "مزون 56",
                "Mazoon 56",
                "mazoon-56",
                "نظام مفصلي عازل للحرارة (Thermal Break) يوفر أداءً عالياً في العزل.",
                "A thermal break hinged system that provides high thermal insulation performance.",
            ),
        ]

        products = []
        for name_ar, name_en, slug, desc_ar, desc_en in products_data:
            product, created = Product.objects.get_or_create(
                slug=slug,
                defaults={
                    "name_ar": name_ar,
                    "name_en": name_en,
                    "description_ar": desc_ar,
                    "description_en": desc_en,
                    "price": 50.0,
                    "is_active": True,
                },
            )
            if not created:
                updated = False
                if not product.name_en:
                    product.name_en = name_en
                    updated = True
                if not product.description_ar:
                    product.description_ar = desc_ar
                    updated = True
                if not product.description_en:
                    product.description_en = desc_en
                    updated = True
                if updated:
                    product.save()

            products.append(product)

        self.stdout.write(self.style.SUCCESS(f"Created/updated {len(products)} product."))

        # -------------------------
        # BLOG POSTS (AR + EN)
        # -------------------------
        blog_posts_data = [
            {
                "slug": "welcome-to-mazoon-blog",
                "title_ar": "مرحبا بكم في مدونة مزون ألمنيوم",
                "title_en": "Welcome to Mazoon Aluminum blog",
                "body_ar": "هذه أول تدوينة في منصة مزون ألمنيوم لعرض الأنظمة، المنتجات، والأخبار التقنية.",
                "body_en": "This is the first post in Mazoon Aluminum blog to showcase systems, product, and technical news.",
                "meta_title_ar": "مدونة مزون ألمنيوم – التدوينة الأولى",
                "meta_title_en": "Mazoon Aluminum blog – first post",
                "meta_description_ar": "تعرّف على مدونة مزون ألمنيوم وأحدث الأخبار حول أنظمة النوافذ والأبواب.",
                "meta_description_en": "Discover Mazoon Aluminum blog and the latest news about window and door systems.",
            },
            {
                "slug": "what-is-mazoon-45",
                "title_ar": "ما هو نظام مزون 45؟",
                "title_en": "What is Mazoon 45 system?",
                "body_ar": "شرح كامل لنظام مزون 45 المفصلي واستخداماته في النوافذ والأبواب.",
                "body_en": "A full explanation of Mazoon 45 hinged system and its use in windows and doors.",
                "meta_title_ar": "نظام مزون 45 المفصلي",
                "meta_title_en": "Mazoon 45 hinged system",
                "meta_description_ar": "تعرف على مزايا نظام مزون 45 المفصلي ولماذا يناسب المشاريع الحديثة.",
                "meta_description_en": "Learn about the advantages of Mazoon 45 hinged system and why it fits modern projects.",
            },
            {
                "slug": "mazoon46-vs-mazoon56",
                "title_ar": "مقارنة بين مزون 46 ومزون 56",
                "title_en": "Comparison between Mazoon 46 and Mazoon 56",
                "body_ar": "مقارنة تفصيلية بين نظام مزون 46 ونظام مزون 56 من حيث العزل والأداء والتطبيقات.",
                "body_en": "A detailed comparison between Mazoon 46 and Mazoon 56 in terms of insulation, performance, and applications.",
                "meta_title_ar": "مقارنة مزون 46 ومزون 56",
                "meta_title_en": "Mazoon 46 vs Mazoon 56",
                "meta_description_ar": "اقرأ مقارنة عملية بين نظامي مزون 46 ومزون 56 لاختيار الأنسب لمشروعك.",
                "meta_description_en": "Read a practical comparison between Mazoon 46 and Mazoon 56 to choose the best for your project.",
            },
        ]

        posts = []
        for data in blog_posts_data:
            post, created = BlogPost.objects.get_or_create(
                slug=data["slug"],
                defaults={
                    "title_ar": data["title_ar"],
                    "title_en": data["title_en"],
                    "body_ar": data["body_ar"],
                    "body_en": data["body_en"],
                    "meta_title_ar": data["meta_title_ar"],
                    "meta_title_en": data["meta_title_en"],
                    "meta_description_ar": data["meta_description_ar"],
                    "meta_description_en": data["meta_description_en"],
                    "is_published": True,
                    "published_at": timezone.now(),
                },
            )

            if not created:
                updated = False
                for field in [
                    "title_ar",
                    "title_en",
                    "body_ar",
                    "body_en",
                    "meta_title_ar",
                    "meta_title_en",
                    "meta_description_ar",
                    "meta_description_en",
                ]:
                    if not getattr(post, field):
                        setattr(post, field, data[field])
                        updated = True
                if updated:
                    post.save()

            # ربط الكاتيجوري والتاج
            post.categories.set(categories[:2])
            post.tags.set(tags[:3])

            posts.append(post)

        self.stdout.write(self.style.SUCCESS(f"Created/updated {len(posts)} blog posts."))

        self.stdout.write(self.style.SUCCESS("Website data (AR + EN) seeding completed successfully!"))
