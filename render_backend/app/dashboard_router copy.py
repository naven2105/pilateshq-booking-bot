"""
dashboard_router.py – Phase 6+7 (Final – Weekly + Monthly)
────────────────────────────────────────────
• /dashboard/weekly-summary   – from Apps Script weekly job
• /dashboard/monthly-summary  – from Apps Script monthly job
Sends WhatsApp via approved template: admin_generic_alert_us
────────────────────────────────────────────
"""

import os
import logging
from flask import Blueprint, request, jsonify
from .utils import send_whatsapp_template

bp = Blueprint("dashboard_bp", __name__)
log = logging.getLogger(__name__)

NADINE_WA = os.getenv("NADINE_WA", "")
TPL_ADMIN_ALERT = "admin_generic_alert_us"
DEFAULT_LANG = os.getenv("TEMPLATE_LANG", "en_US")

@bp.route("/weekly-summary", methods=["POST"])
def weekly_summary():
    try:
        data = request.get_json(force=True)
        revenue = float(data.get("revenue", 0))
        attendance = str(data.get("attendance", "0"))
        outstanding = float(data.get("outstanding", 0))
        count = int(data.get("outstanding_count", 0))
        chart = data.get("chart_url", "").strip()

        summary_text = (
            f"PilatesHQ Weekly: Revenue R{revenue:,.0f}, "
            f"Attendance {attendance}%, "
            f"Outstanding {count} (R{outstanding:,.0f}). "
            f"Chart: {chart}"
        )

        send_whatsapp_template(NADINE_WA, TPL_ADMIN_ALERT, DEFAULT_LANG, [summary_text])
        log.info("✅ Weekly dashboard summary sent.")
        return jsonify({"ok": True, "message": "Summary sent"})
    except Exception as e:
        log.error(f"❌ Weekly dashboard error: {e}")
        return jsonify({"ok": False, "error": str(e)})

@bp.route("/monthly-summary", methods=["POST"])
def monthly_summary():
    try:
        data = request.get_json(force=True)
        month_label = data.get("month_label", "")
        revenue = float(data.get("revenue", 0))
        outstanding = float(data.get("outstanding", 0))
        mom_change = float(data.get("mom_change", 0))
        top_debtors = data.get("top_debtors", [])  # [{name, amount}]
        chart = data.get("chart_url", "").strip()

        # Build compact, template-safe text (no newlines/tabs)
        # Include top 3 debtors if available
        debt_txt = ""
        if top_debtors:
            parts = [f"{d.get('name','?')} R{float(d.get('amount',0)):.0f}" for d in top_debtors]
            debt_txt = " | Debtors: " + "; ".join(parts)

        msg = (
            f"PilatesHQ {month_label} Snapshot: "
            f"Revenue R{revenue:,.0f} ({mom_change:+.1f}% MoM), "
            f"Outstanding R{outstanding:,.0f}{debt_txt}. "
            f"Chart: {chart}"
        )

        send_whatsapp_template(NADINE_WA, TPL_ADMIN_ALERT, DEFAULT_LANG, [msg])
        log.info("✅ Monthly dashboard summary sent.")
        return jsonify({"ok": True, "message": "Summary sent"})
    except Exception as e:
        log.error(f"❌ Monthly dashboard error: {e}")
        return jsonify({"ok": False, "error": str(e)})
