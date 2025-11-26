# # portal/signals/notifications.py
#
# from django.contrib.auth import get_user_model
# from django.db.models.signals import post_save
# from django.dispatch import receiver
# from django.urls import reverse
# from django.utils.translation import gettext as _, get_language
#
# from accounting.models import Order
# from core.models import Notification
# from core.services.notifications import create_notification
#
# User = get_user_model()
#
#
# def strip_lang_prefix(path: str) -> str:
#     """
#     يشيل البادئة /ar/ أو /en/ (أو أي لغة حالية) من بداية الرابط،
#     عشان نخزن في النوتفيكشن path محايد لغة، مثل: /accounting/orders/1/
#     """
#     if not path:
#         return path
#
#     lang = get_language() or "en"
#     prefix = f"/{lang}/"  # مثال: /ar/ أو /en/
#
#     if path.startswith(prefix):
#         # نخليها تبدأ من بعد "/ar" أو "/en" مع الإبقاء على "/"
#         return path[len(prefix) - 1 :]  # يحافظ على "/" الأولى قبل بقية الـ path
#
#     return path
#
#
# # ============================
# # إشعارات الطلبات أونلاين فقط
# # ============================
#
# @receiver(post_save, sender=Order)
# def online_order_created_notify_staff(sender, instance, created, **kwargs):
#     """
#     إشعار موظفي المحاسبة عند إنشاء طلب أونلاين من بوابة الزبون.
#     """
#     if not created:
#         return
#
#     order = instance
#
#     if not order.is_online:
#         return
#
#     # 👇 نحدد رابط شاشة الموظفين مرة واحدة، ونشيل بادئة اللغة
#     raw_staff_url = reverse(
#         "accounting:order_detail",
#         kwargs={"pk": order.pk},
#     )
#     staff_url = strip_lang_prefix(raw_staff_url)
#
#     staff_users = User.objects.filter(
#         groups__name="accounting_staff",
#         is_active=True,
#     ).distinct()
#
#     for staff in staff_users:
#         create_notification(
#             recipient=staff,
#             verb=_("تم إنشاء طلب جديد من بوابة الزبون."),
#             target=order,
#             level=Notification.Levels.INFO,
#             url=staff_url,  # 👈 path محايد لغة (مثلاً: /accounting/orders/1/)
#         )
