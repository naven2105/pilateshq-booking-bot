# app/config.py
import os
import logging

# ------------------------------
# WhatsApp Cloud API / Meta
# ------------------------------
# IMPORTANT: set these in Render → Environment
ACCESS_TOKEN     = os.environ.get("ACCESS_TOKEN", "").strip()
PHONE_NUMBER_ID  = os.environ.get("PHONE_NUMBER_ID", "").strip()   # e.g. 802833389569115
VERIFY_TOKEN     = os.environ.get("VERIFY_TOKEN", "testtoken").strip()

# WA Messages endpoint, versioned. (Cloud API auto-upgrades anyway, but keep v21 aligned with docs.)
GRAPH_URL = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages" if PHONE_NUMBER_ID else ""

# ------------------------------
# Admin (single-admin mode is fine)
# ------------------------------
# Can be 062..., +27..., 27… (we normalize elsewhere).
NADINE_WA = os.environ.get("NADINE_WA", "").strip()
# Optional: if you later support multiple admins:
ADMIN_WA_LIST = [x.strip() for x in os.environ.get("ADMIN_WA_LIST", "").split(",") if x.strip()]

# ------------------------------
# Database
# ------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# ------------------------------
# Timezone for all “today/next hour” calculations
# ------------------------------
# Set TZ_NAME in Render → Environment if you need to change from SA time.
TZ_NAME = os.environ.get("TZ_NAME", "Africa/Johannesburg").strip() or "Africa/Johannesburg"
logging.info(f"[CONFIG] TZ_NAME={TZ_NAME}")

# ------------------------------
# Templates (for HSM / outside 24h window)
# ------------------------------
# Keep a simple “admin_update” template that accepts one {{1}} body var.
ADMIN_TEMPLATE_NAME = os.environ.get("ADMIN_TEMPLATE_NAME", "admin_update").strip()
ADMIN_TEMPLATE_LANG = os.environ.get("ADMIN_TEMPLATE_LANG", "en").strip()
