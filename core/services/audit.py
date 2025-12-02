# core/services/audit.py
from __future__ import annotations

from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType

from core.models import AuditLog


def log_event(
    *,
    action: str,
    message: str = "",
    actor=None,
    target: Optional[Any] = None,
    extra: Optional[dict] = None,
) -> AuditLog:
    """
    تسجيل حدث تدقيق (Audit Log).

    المعاملات:
    - action: نوع العملية (مثل: CREATE / UPDATE / DELETE / STATUS_CHANGE ...)
    - message: وصف نصي قابل للقراءة البشرية (يمكن أن يكون بالعربية)
    - actor: المستخدم الذي قام بالعملية، أو None إذا لم يكن هناك مستخدم
    - target: أي كائن (Model Instance) ليتم ربط هذا الحدث به
    - extra: بيانات إضافية اختيارية يتم حفظها ضمن JSON

    الوظائف:
    - يحفظ اسم العملية والوصف.
    - يسجل المستخدم (actor) إذا كان مسجلاً للدخول.
    - يربط الحدث بكائن الهدف (target) باستخدام GenericForeignKey:
        * target_content_type
        * target_object_id
    - يخزن البيانات الإضافية داخل extra كـ JSON.
    """

    data: dict[str, Any] = {
        "action": action,
        "message": message or "",
        "extra": extra or {},
    }

    # --- تسجيل المستخدم (actor) ---
    if actor is not None and getattr(actor, "is_authenticated", False):
        data["actor"] = actor

    # --- ربط الحدث بهدف معين (target model instance) ---
    if target is not None:
        # ContentType للكلاس الحقيقي للكائن (حتى مع الوراثة)
        ct = ContentType.objects.get_for_model(target)

        obj_id = getattr(target, "pk", None) or getattr(target, "id", None)
        if obj_id is not None:
            data["target_content_type"] = ct
            data["target_object_id"] = str(obj_id)

    # إنشاء سجل الأوديت فعليًا
    return AuditLog.objects.create(**data)
