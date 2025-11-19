# core/services/numbering.py
from __future__ import annotations

from dataclasses import dataclass

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


def _get_config_for_instance(instance) -> NumberingConfig:
    """
    Load numbering config for a given model instance from NumberingScheme.
    """
    scheme = NumberingScheme.get_for_instance(instance)
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


def generate_number_for_instance(instance) -> str:
    """
    Generate a human-friendly number for any model instance,
    based on NumberingScheme rows stored in the database.

    Usage:
        invoice.number = generate_number_for_instance(invoice)
    """
    cfg = _get_config_for_instance(instance)
    now = timezone.now()

    # Determine period for grouping sequences
    period = _get_period(cfg.reset)

    # Key is the model label, e.g. "accounting.Invoice"
    key = instance._meta.label

    # Get next integer in sequence
    seq = _next_sequence_value(key=key, period=period, start=cfg.start)

    # Build final string from pattern
    number = cfg.pattern.format(
        year=now.year,
        month=now.month,
        day=now.day,
        seq=seq,
    )

    return number
