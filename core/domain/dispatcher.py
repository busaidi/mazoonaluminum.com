from collections import defaultdict
from typing import Callable, Dict, List, TypeVar

E = TypeVar("E")

# event_type -> [handlers...]
_HANDLERS: Dict[type, List[Callable[[E], None]]] = defaultdict(list)


def register_handler(event_type: type[E], handler: Callable[[E], None]) -> None:
    """
    تسجّل هاندلر لحدث معيّن.
    - event_type: كلاس الحدث (مثلاً InvoicePaidEvent)
    - handler: دالة أو فانكشن يستقبل instance من الحدث
    """
    _HANDLERS[event_type].append(handler)


def dispatch(event: E) -> None:
    """
    يرسل الحدث لكل الهاندلرات المسجّلة لهذا النوع.
    """
    for handler in _HANDLERS.get(type(event), []):
        handler(event)
