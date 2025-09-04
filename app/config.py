# app/config.py
import os

# ── Meta / WhatsApp Cloud API ────────────────────────────────────────────────
ACCESS_TOKEN     = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID  = os.environ.get("PHONE_NUMBER_ID", "")  # e.g. "802833389569115"
VERIFY_TOKEN     = os.environ.get("VERIFY_TOKEN", "testtoken")

# Graph endpoint (version can be bumped without code changes)
GRAPH_VER = os.environ.get("GRAPH_VER", "v21.0")
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VER}/{PHONE_NUMBER_ID}/messages"

# ── Admin (leave blank during testing if you don’t want admin messages) ──────
# Accepts 0XXXXXXXXX / 27XXXXXXXXX / +27XXXXXXXXX. We normalize before use.
NADINE_WA = os.environ.get("NADINE_WA", "").strip()

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Local timezone used in SQL (PostgreSQL AT TIME ZONE) ─────────────────────
# Keep this in sync with your studio’s local time.
TZ_NAME = os.environ.get("TZ_NAME", "Africa/Johannesburg")

# ── Templates for outbound messages (outside 24h window) ─────────────────────
# Keep a very simple, generic template that accepts one big text variable.
# Suggested approved template:
#   Name: admin_update
#   Language: en
#   Body: "{{1}}"
ADMIN_TEMPLATE_NAME = os.environ.get("ADMIN_TEMPLATE_NAME", "admin_update")
ADMIN_TEMPLATE_LANG = os.environ.get("ADMIN_TEMPLATE_LANG", "en")
