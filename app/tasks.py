# app/tasks.py
"""
Shim to register all background task routes.
"""

from __future__ import annotations
from .admin_reminders import register_admin_reminders
from .client_reminders import register_client_reminders

def register_tasks(app):
    register_admin_reminders(app)
    register_client_reminders(app)
