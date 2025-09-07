# app/config.py
from __future__ import annotations

import os
import logging
from typing import List, Dict


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers to safely read environment variables with casting
# ─────────────────────────────────────────────────────────────────────────────

def _getenv_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def _getenv_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    val = val.strip().lower()
    return val in ("1", "true", "yes", "on")

def _getenv_int(name: str, default: int = 0) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val.strip())
    except Exception:
        return default

def _getenv_list(name: str, default: List[str] | None = None) -> List[str]:
    """
    Comma-separated list → ['a','b',...]; trims whitespace; ignores empties.
    Example: ADMIN_NUMBERS="+2762..., 2761..., 0620..."
    """
    raw = os.environ.get(name)
    if not raw:
        return list(default or [])
    return [x.strip() for x in raw.split(",") if x.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
# Render supports e.g. LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
_LOG_LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR":    logging.ERROR,
    "WARNING":  logging.WARNING,
    "INFO":     logging.INFO,
    "DEBUG":    logging.DEBUG,
}
LOG_LEVEL_NAME = _getenv_str("LOG_LEVEL", "INFO").upper()
LOG_LEVEL      = _LOG_LEVEL_MAP.get(LOG_LEVEL_NAME, logging.INFO)  # Fallback sensibly


# ─────────────────────────────────────────────────────────────────────────────
# Meta / WhatsApp Cloud API
# ─────────────────────────────────────────────────────────────────────────────
ACCESS_TOKEN    = _getenv_str("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = _getenv_str("PHONE_NUMBER_ID", "")   # e.g. "802833389569115"
VERIFY_TOKEN    = _getenv_str("VERIFY_TOKEN", "testtoken")

# Graph API version is overridable without code changes
GRAPH_VER = _getenv_str("GRAPH_VER", "v21.0").lower().replace("v", "v")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VER}/{PHONE_NUMBER_ID}/messages"

# Safety: if someone forgets PHONE_NUMBER_ID, GRAPH_URL will be malformed.
# We keep it as-is but most senders should guard against empty ACCESS_TOKEN/PHONE_NUMBER_ID.


# ─────────────────────────────────────────────────────────────────────────────
# Admins
# ─────────────────────────────────────────────────────────────────────────────
# Support single or multiple admins. (Numbers can be 0XXXXXXXXX / 27XXXXXXXXX / +27XXXXXXXXX;
# we normalize them later at send time.)
NADINE_WA     = _getenv_str("NADINE_WA", "")  # preserved for backward-compat
ADMIN_NUMBERS = _getenv_list("ADMIN_NUMBERS", default=([NADINE_WA] if NADINE_WA else []))
# Example env:
#   ADMIN_NUMBERS="+27627597357, 2763..., 073..."


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────
DATABASE_URL = _getenv_str("DATABASE_URL", "")


# ─────────────────────────────────────────────────────────────────────────────
# Timezone (used in SQL via AT TIME ZONE)
# Keep in sync with local studio time
# ─────────────────────────────────────────────────────────────────────────────
TZ_NAME = _getenv_str("TZ_NAME", "Africa/Johannesburg")


# ─────────────────────────────────────────────────────────────────────────────
# Features & Limits (toggles you might want to expose via env)
# ─────────────────────────────────────────────────────────────────────────────
# Whether to use WhatsApp *templates* for certain outbound (outside 24h window)
USE_TEMPLATES = _getenv_bool("USE_TEMPLATES", False)

# Max rows shown in admin text summaries (defensive; your code may ignore)
ADMIN_SUMMARY_MAX_ROWS = _getenv_int("ADMIN_SUMMARY_MAX_ROWS", 50)

# Whether to include client names in admin pushes (you can still override per-request)
ADMIN_INCLUDE_NAMES_DEFAULT = _getenv_bool("ADMIN_INCLUDE_NAMES_DEFAULT", True)


# ─────────────────────────────────────────────────────────────────────────────
# Template names (central registry so your code can reference config only)
# Make sure each exists & is approved in Meta Business Manager before use.
# Keep variable counts MINIMAL to avoid “floating/dangling parameter” rejects.
# ─────────────────────────────────────────────────────────────────────────────
TEMPLATE_LANG = _getenv_str("TEMPLATE_LANG", "en")  # or "en_ZA" if that’s how you created them

TEMPLATES: Dict[str, dict] = {
    # Hourly update to admin (Utility): 2 variables
    # Body: "Next hour session: {{1}}.\nStatus: {{2}}."
    "admin_hourly_update": {
        "name": _getenv_str("TPL_ADMIN_HOURLY", "admin_hourly_update"),
        "lang": TEMPLATE_LANG,
        "vars": 2,
    },

    # Admin daily recap at 20:00 (Utility): keep variables LOW; 1 variable recommended
    # Body: "Daily recap: {{1}}"   (we pass a compact one-line)
    "admin_20h00": {
        "name": _getenv_str("TPL_ADMIN_20H00", "admin_20h00"),
        "lang": TEMPLATE_LANG,
        "vars": 1,
    },

    # Client next-hour reminder (Utility): 1 variable
    # Body: "Reminder: Your Pilates session starts at {{1}} today."
    "session_next_hour": {
        "name": _getenv_str("TPL_NEXT_HOUR", "session_next_hour"),
        "lang": TEMPLATE_LANG,
        "vars": 1,
    },

    # Client tomorrow reminder (Utility): 1 variable
    # Body: "Reminder: Your Pilates session is tomorrow at {{1}}."
    "session_tomorrow": {
        "name": _getenv_str("TPL_TOMORROW", "session_tomorrow"),
        "lang": TEMPLATE_LANG,
        "vars": 1,
    },

    # Admin broadcast “cancel all sessions (sick/unavailable)” (Utility): 1 variable
    # Body: "{{1}}" (we pass the text we want)
    "admin_cancel_all": {
        "name": _getenv_str("TPL_ADMIN_CANCEL_ALL", "admin_cancel_all_sessions_admin_sick_unavailable"),
        "lang": TEMPLATE_LANG,
        "vars": 1,
    },

    # Generic admin update (Utility): 1 variable → Body: "{{1}}"
    "admin_update": {
        "name": _getenv_str("TPL_ADMIN_UPDATE", "admin_update"),
        "lang": TEMPLATE_LANG,
        "vars": 1,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Sanity logging (optional; safe to keep here)
# ─────────────────────────────────────────────────────────────────────────────
logging.getLogger().setLevel(LOG_LEVEL)
logging.info(f"[config] LOG_LEVEL={LOG_LEVEL_NAME}")
logging.info(f"[config] GRAPH_VER={GRAPH_VER} PHONE_NUMBER_ID={'set' if PHONE_NUMBER_ID else 'missing'}")
logging.info(f"[config] ADMIN_NUMBERS={ADMIN_NUMBERS or '[]'} TZ_NAME={TZ_NAME}")
logging.info(f"[config] USE_TEMPLATES={USE_TEMPLATES} TEMPLATE_LANG={TEMPLATE_LANG}")
