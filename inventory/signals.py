# inventory/signals.py
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import StockMove
from .services import apply_stock_move_on_delete


@receiver(post_delete, sender=StockMove)
def stockmove_post_delete(sender, instance: StockMove, **kwargs):
    """
    عند حذف حركة مخزون، نعكس أثرها على المخزون *فقط إذا كانت DONE*.

    ملاحظة:
      - منطق تطبيق الحركة عند الإنشاء / تعديل الحالة أصبح داخل
        StockMove.save() عبر apply_stock_move_status_change.
      - لذلك لم نعد بحاجة لـ post_save signal هنا.
    """
    apply_stock_move_on_delete(instance)
