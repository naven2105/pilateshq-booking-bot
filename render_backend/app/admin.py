"""
admin.py
────────
Thin entrypoint.
Delegates all admin commands to admin_core.
"""

from .admin_core import handle_admin_action
