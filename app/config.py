# app/config.py
from __future__ import annotations

import os
import logging


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


# ─────────────────────────────────────────────────────────────────────────────
# Meta / WhatsApp Cloud API
# ─────────────────────────────────────────────────────────────────────────────

ACCESS_TOKEN    = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")  # e.g. "802833389569115"

# Public verification token for the webhook challenge
VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "testtoken")

# Graph API version & endpoint
# (Meta keeps auto-upgrading old versions; feel free to set GRAPH_VER=v23.0)
GRAPH_VER = os.environ.get("GRAPH_VER", "v23.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VER}/{PHONE_NUMBER_ID}/messages"

# Template usage toggle (outside 24h window, or when you prefer templates)
USE_TEMPLATES = env_bool("USE_TEMPLATES", True)

# Meta language code for templates (examples: "en", "en_US", "en_GB", "en_ZA")
TEMPLATE_LANG = os.environ.get("TEMPLATE_LANG", "en")

# Approved template names (override via env if your names differ)
# Keep these in sync with what you actually got approved in Business Manager.
TPL_ADMIN_HOURLY     = os.environ.get("TPL_ADMIN_HOURLY",     "admin_hourly_update")
TPL_ADMIN_20H00      = os.environ.get("TPL_ADMIN_20H00",      "admin_20h00")
TPL_NEXT_HOUR        = os.environ.get("TPL_NEXT_HOUR",        "session_next_hour")
TPL_TOMORROW         = os.environ.get("TPL_TOMORROW",         "session_tomorrow")
TPL_ADMIN_CANCEL_ALL = os.environ.get("TPL_ADMIN_CANCEL_ALL", "admin_cancel_all_sessions_admin_sick_unavailable")
TPL_ADMIN_UPDATE     = os.environ.get("TPL_ADMIN_UPDATE",     "admin_update")


# ─────────────────────────────────────────────────────────────────────────────
# Admin / Recipients
# ─────────────────────────────────────────────────────────────────────────────
# Single-admin mode is fine. Accept 0XXXXXXXXX / 27XXXXXXXXX / +27XXXXXXXXX.
NADINE_WA = os.environ.get("NADINE_WA", "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ─────────────────────────────────────────────────────────────────────────────
# Local Timezone used in SQL (PostgreSQL AT TIME ZONE)
# ─────────────────────────────────────────────────────────────────────────────

# Keep this aligned with your studio’s local time.
TZ_NAME = os.environ.get("TZ_NAME", "Africa/Johannesburg")


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

# Render often sets LOG_LEVEL. Respect it if present.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
    LOG_LEVEL = "INFO"

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
