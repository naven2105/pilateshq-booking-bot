# app/tasks.py
"""
Keeps backwards compatibility.
All reminder/task logic now lives in reminders.py.
"""

from __future__ import annotations
from .reminders import register_reminders

def register_tasks(app):
    # Delegate to reminders
    register_reminders(app)
