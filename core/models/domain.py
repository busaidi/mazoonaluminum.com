# core/models/domain.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

from django.db import models, transaction

from core.domain.dispatcher import emit as emit_domain_event
from core.domain.events import DomainEvent


class DomainEventsMixin(models.Model):
    """
    Abstract Django model that can:
      - emit domain events
      - execute lifecycle hooks
      - execute state transition hooks

    Hooks are discovered via decorators defined in core.domain.hooks:
      - @on_lifecycle("created" | "updated" | "deleted")
      - @on_transition(from_state, to_state, field_name="status")

    The discovery of hook methods is cached at class-definition time
    using __init_subclass__, so runtime overhead is very small.
    """

    # These attributes will be populated per subclass in __init_subclass__
    _lifecycle_hooks: Dict[str, List[str]] = {}
    _transition_hooks: List[Tuple[str, Any, Any, str]] = []

    class Meta:
        abstract = True

    # ------------------------------------------------------------------
    # Class-level hook discovery & caching
    # ------------------------------------------------------------------
    def __init_subclass__(cls, **kwargs):
        """
        Called once per subclass definition.
        We use this to discover and cache hook methods.
        """
        super().__init_subclass__(**kwargs)

        lifecycle_hooks: Dict[str, List[str]] = {}
        transition_hooks: List[Tuple[str, Any, Any, str]] = []

        # Inherit hooks from base classes (if any)
        for base in cls.__mro__[1:]:
            if hasattr(base, "_lifecycle_hooks"):
                for name, methods in getattr(base, "_lifecycle_hooks", {}).items():
                    lifecycle_hooks.setdefault(name, []).extend(methods)

            if hasattr(base, "_transition_hooks"):
                for item in getattr(base, "_transition_hooks", []):
                    transition_hooks.append(item)

        # Discover hooks defined on this class
        for attr_name, attr_value in cls.__dict__.items():
            if not callable(attr_value):
                continue

            lifecycle_event = getattr(attr_value, "__lifecycle_event__", None)
            if lifecycle_event is not None:
                lifecycle_hooks.setdefault(lifecycle_event, []).append(attr_name)

            transition_meta = getattr(attr_value, "__transition__", None)
            if transition_meta is not None:
                field_name, from_state, to_state = transition_meta
                transition_hooks.append((field_name, from_state, to_state, attr_name))

        cls._lifecycle_hooks = lifecycle_hooks
        cls._transition_hooks = transition_hooks

    # ------------------------------------------------------------------
    # Domain events
    # ------------------------------------------------------------------
    def emit(self, event: DomainEvent) -> None:
        """
        Emit a domain event using the global dispatcher.
        """
        emit_domain_event(event)

    # ------------------------------------------------------------------
    # Internal helpers for running hooks
    # ------------------------------------------------------------------
    def _run_lifecycle_hooks(self, event_name: str) -> None:
        """
        Run all lifecycle hooks registered for the given event name.
        """
        method_names = self._lifecycle_hooks.get(event_name, [])
        for method_name in method_names:
            method = getattr(self, method_name, None)
            if callable(method):
                method()

    def _run_transition_hooks(self, field_name: str, old: Any, new: Any) -> None:
        """
        Run all transition hooks registered for the given field and state change.
        """
        for hook_field, from_state, to_state, method_name in self._transition_hooks:
            if hook_field == field_name and from_state == old and to_state == new:
                method = getattr(self, method_name, None)
                if callable(method):
                    method()

    # ------------------------------------------------------------------
    # Overridden save/delete
    # ------------------------------------------------------------------
    def save(self, *args, **kwargs) -> None:
        """
        Override save() to:
          - detect create vs update
          - detect transitions of "status" field (if present)
          - run lifecycle and transition hooks after DB commit
        """
        is_create = self._state.adding

        old_values: Dict[str, Optional[Any]] = {}

        # Track "status" transitions by default if present
        if not is_create and hasattr(self, "status"):
            model_cls: Type[models.Model] = type(self)
            old = model_cls.objects.filter(pk=self.pk).values("status").first()
            if old is not None:
                old_values["status"] = old["status"]

        super().save(*args, **kwargs)

        def run_hooks() -> None:
            # Lifecycle hooks
            if is_create:
                self._run_lifecycle_hooks("created")
            else:
                self._run_lifecycle_hooks("updated")

            # Transition hooks for "status"
            if "status" in old_values and hasattr(self, "status"):
                old_status = old_values["status"]
                new_status = getattr(self, "status", None)
                if old_status != new_status:
                    self._run_transition_hooks("status", old_status, new_status)

        # Run hooks only after the transaction has been committed
        transaction.on_commit(run_hooks)

    def delete(self, *args, **kwargs) -> None:
        """
        Override delete() to run 'deleted' lifecycle hooks after commit.
        """
        super().delete(*args, **kwargs)

        def run_hooks() -> None:
            self._run_lifecycle_hooks("deleted")

        transaction.on_commit(run_hooks)


class StatefulDomainModel(DomainEventsMixin):
    """
    Optional base model for models that have a 'status' field and
    want a domain-level method to change it.

    - STATUS_FIELD_NAME: which field is considered the "state" field.
      (default: "status")
    """

    class Meta:
        abstract = True

    STATUS_FIELD_NAME: str = "status"

    def change_state(
        self,
        new_state: Any,
        *,
        save: bool = True,
        update_fields: Optional[List[str]] = None,
    ) -> None:
        """
        Domain-level method to change the state field.

        - Updates the state field.
        - Saves the model (if save=True).
        - All hooks are triggered by the regular save() override.
        """
        field_name = self.STATUS_FIELD_NAME

        setattr(self, field_name, new_state)

        if save:
            if update_fields is None:
                update_fields = [field_name]
            super().save(update_fields=update_fields)
        # If save=False, the caller is responsible for calling save().
