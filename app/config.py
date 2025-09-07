# app/config.py
import os

# ── Meta / WhatsApp Cloud API ────────────────────────────────────────────────
ACCESS_TOKEN     = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID  = os.environ.get("PHONE_NUMBER_ID", "")  # e.g. "802833389569115"
VERIFY_TOKEN     = os.environ.get("VERIFY_TOKEN", "testtoken")

# Graph endpoint (version can be bumped without code changes)
GRAPH_VER = os.environ.get("GRAPH_VER", "v21.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VER}/{PHONE_NUMBER_ID}/messages"

# ── Admin numbers ────────────────────────────────────────────────────────────
# Comma-separated env var, e.g. "27620469153,27843131635"
ADMIN_NUMBERS = [
    n.strip() for n in os.environ.get("ADMIN_NUMBERS", "").split(",") if n.strip()
]

# Legacy single-admin mode (optional fallback)
NADINE_WA = os.environ.get("NADINE_WA", "").strip()
if NADINE_WA and NADINE_WA not in ADMIN_NUMBERS:
    ADMIN_NUMBERS.append(NADINE_WA)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Local timezone for schedule logic (PostgreSQL AT TIME ZONE) ─────────────
TZ_NAME = os.environ.get("TZ_NAME", "Africa/Johannesburg")

# ── Templates for outbound messages (outside 24h window) ─────────────────────
# Keep a very simple, generic template that accepts one big text variable.
# Suggested approved template:
#   Name: admin_update
#   Language: en
#   Body: "{{1}}"
ADMIN_TEMPLATE_NAME = os.environ.get("ADMIN_TEMPLATE_NAME", "admin_update")
ADMIN_TEMPLATE_LANG = os.environ.get("ADMIN_TEMPLATE_LANG", "en")

# ── Flags ────────────────────────────────────────────────────────────────────
# If True → try to use templates when possible, else fallback to plain text
USE_TEMPLATES = os.environ.get("USE_TEMPLATES", "0") in ("1", "true", "True")

# Default template language code for WhatsApp Cloud API
TEMPLATE_LANG = os.environ.get("TEMPLATE_LANG", "en")
