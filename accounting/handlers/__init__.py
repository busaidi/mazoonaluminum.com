# accounting/handlers/__init__.py
"""
Entry point for accounting domain event handlers.

This module is imported from AccountingConfig.ready()
to ensure all handlers are registered at Django startup.
"""

from . import invoice  # noqa
# from . import payment  # noqa  # (future)
from . import order  # noqa    # (future)
