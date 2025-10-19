"""
dashboard_router.py – Phase 6 (Final – Compact Summary)
────────────────────────────────────────────
Handles weekly studio dashboard summaries.
Receives data from Google Apps Script and
sends WhatsApp summary to Nadine using the
approved template: admin_generic_alert_us

✅ Compact one-line summary (Meta-safe)
────────────────────────────────────────────
"""

import os
import logging
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template

bp = Blueprint("dashboard_bp", __name__)
log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
NADINE_WA = os.getenv("NADINE_WA", "")
TPL_WEEKLY_SUMMARY = "admin_generic_alert_us"
DEFAULT_LANG = os.getenv("TEMPLATE_LANG", "en_US")

# ── Route: /dashboard/weekly-summary ─────────────────────────
@bp.route("/weekly-summary", methods=["POST"])
def weekly_summary():
    try:
        data = request.get_json(force=True)
        revenue = float(data.get("revenue", 0))
        attendance = str(data.get("attendance", "0"))
        outstanding = float(data.get("outstanding", 0))
        count = int(data.get("outstanding_count", 0))
        chart = data.get("chart_url", "").strip()

        # ✅ Compact one-line summary (Meta-safe)
        summary_text = (
            f"PilatesHQ Weekly: Revenue R{revenue:,.0f}, "
            f"Attendance {attendance}%, "
            f"Outstanding {count} (R{outstanding:,.0f}). "
            f"Chart: {chart}"
        )

        # ✅ Send using approved template (safe format)
        send_whatsapp_template(
            NADINE_WA,
            TPL_WEEKLY_SUMMARY,
            DEFAULT_LANG,
            [summary_text],
        )

        log.info("✅ Weekly dashboard summary sent via admin_generic_alert_us.")
        return jsonify({"ok": True, "message": "Summary sent"})

    except Exception as e:
        log.error(f"❌ Dashboard summary error: {e}")
        return jsonify({"ok": False, "error": str(e)})
