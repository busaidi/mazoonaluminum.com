# core/services/numbering.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import NumberSequence, NumberingScheme


@dataclass
class NumberingConfig:
    """
    Internal config holder resolved from NumberingScheme.
    """
    field: str
    pattern: str
    reset: str
    start: int


def _get_config_for_instance(instance, field_name: str = "number") -> NumberingConfig:
    """
    Load numbering config for a given model instance from NumberingScheme.
    """
    scheme = NumberingScheme.get_for_instance(instance, field_name=field_name)
    return NumberingConfig(
        field=scheme.field_name,
        pattern=scheme.pattern,
        reset=scheme.reset,
        start=scheme.start,
    )


def _get_period(reset: str) -> str:
    """
    Build the period string based on 'reset' policy.
    """
    now = timezone.now()

    if reset == NumberingScheme.ResetPolicy.YEAR:
        return str(now.year)  # "2025"
    elif reset == NumberingScheme.ResetPolicy.MONTH:
        return f"{now.year}-{now.month:02d}"  # "2025-11"
    else:
        # "never" → single global sequence
        return ""


def _next_sequence_value(key: str, period: str, start: int) -> int:
    """
    Return the next sequence integer for the given key+period.
    Uses select_for_update to avoid race conditions.
    """
    with transaction.atomic():
        seq_obj, created = NumberSequence.objects.select_for_update().get_or_create(
            key=key,
            period=period,
            defaults={"last_value": start - 1},
        )
        seq_obj.last_value += 1
        seq_obj.save(update_fields=["last_value"])
        return seq_obj.last_value


def generate_number_for_instance(
    instance,
    field_name: str = "number",
) -> str:
    """
    Generate a human-friendly number for any model instance,
    based on NumberingScheme rows stored in the database.

    Usage:
        invoice.number = generate_number_for_instance(invoice)
        move.number    = generate_number_for_instance(move, field_name="number")
    """
    cfg = _get_config_for_instance(instance, field_name=field_name)
    now = timezone.now()

    # Determine period for grouping sequences
    period = _get_period(cfg.reset)

    # Key is the model label, e.g. "accounting.Invoice"
    key = instance._meta.label

    # Get next integer in sequence
    seq = _next_sequence_value(key=key, period=period, start=cfg.start)

    # ==== Build context for pattern ====
    context: dict[str, Any] = {}

    # 1) سياق خاص من الموديل (مثل prefix في StockMove)
    base_ctx: dict[str, Any] = {}
    if hasattr(instance, "get_numbering_context"):
        try:
            raw_ctx = instance.get_numbering_context() or {}
            if isinstance(raw_ctx, dict):
                base_ctx = raw_ctx
        except Exception:
            # ما نحب نخلي الترقيم يطيح عشان سياق موديل فيه خطأ
            base_ctx = {}

    context.update(base_ctx)

    # 2) قيم زمنية افتراضية
    context.setdefault("year", now.year)
    context.setdefault("month", now.month)  # يمكن تستخدم {month:02d} في pattern
    context.setdefault("day", now.day)

    # 3) prefix افتراضي (عشان نتفادى KeyError لو الـ pattern فيه {prefix})
    context.setdefault("prefix", "")

    # 4) رقم التسلسل
    context["seq"] = seq

    # Build final string from pattern
    number = cfg.pattern.format(**context)

    return number
