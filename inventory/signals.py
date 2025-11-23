# inventory/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import StockMove
from .services import apply_stock_move_on_create, apply_stock_move_on_delete


@receiver(post_save, sender=StockMove)
def stockmove_post_save(sender, instance: StockMove, created, **kwargs):
    """
    عند إنشاء حركة مخزون جديدة، يتم تحديث مستويات المخزون.
    - لا نطبّق شيء عند التعديل حالياً (للتبسيط).
    """
    if not created:
        return

    apply_stock_move_on_create(instance)


@receiver(post_delete, sender=StockMove)
def stockmove_post_delete(sender, instance: StockMove, **kwargs):
    """
    عند حذف حركة مخزون، نعكس أثرها على المخزون.
    """
    apply_stock_move_on_delete(instance)
