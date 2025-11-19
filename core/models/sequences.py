# core/models/sequences.py
from django.db import models


class NumberSequence(models.Model):
    """
    Stores the last used sequence value for a given model (key) and period.

    Example:
    - key: "accounting.Invoice"
    - period: "2025" (if reset="year")
    - last_value: 42 → next will be 43
    """

    key = models.CharField(max_length=100)
    period = models.CharField(max_length=16, blank=True)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("key", "period")

    def __str__(self) -> str:
        if self.period:
            return f"{self.key} [{self.period}] → {self.last_value}"
        return f"{self.key} → {self.last_value}"
