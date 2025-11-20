# core/domain/models.py
"""
Compatibility layer حول core.models.domain.

يفضّل مستقبلاً الاستيراد مباشرة من:
    from core.models.domain import DomainModel, StatefulDomainModel
"""

from core.models.domain import DomainModel as _DomainModel, StatefulDomainModel as _StatefulDomainModel


class DomainModel(_DomainModel):
    class Meta:
        abstract = True


class StatefulDomainModel(_StatefulDomainModel):
    class Meta:
        abstract = True
