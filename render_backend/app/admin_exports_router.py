"""
admin_exports_router.py – Phase 30S (Standardised “(x)” markers)
────────────────────────────────────────────────────────────
Purpose:
 • Provide admin-facing export endpoints that proxy GAS and
   render a consistent summary string where any session with
   status 'rescheduled' is marked with "(x)" after the time.

Endpoints:
 • POST /admin/export/today  { wa_number? }
 • POST /admin/export/week   { wa_number? }

Notes:
 • Requires GAS_WEBHOOK_URL env var to be set to the GAS WebApp.
 • Backward compatible with existing GAS responses that already
   include `summary`; we prefer rebuilding from `sessions` if
   available to guarantee “(x)” notation as a standard.
────────────────────────────────────────────────────────────
"""

import os
import logging
import requests
from flask import Blueprint, request, jsonify

bp = Blueprint("admin_exports_bp", __name__)
log = logging.getLogger(__name__)

GAS_WEBHOOK_URL = os.getenv("GAS_WEBHOOK_URL", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "35"))
TEMPLATE_LANG = os.getenv("TEMPLATE_LANG", "en_US")


def _fmt_line(time_str: str, client_name: str, session_type: str, status: str) -> str:
    """
    Format a single session line with marker "(x)" for rescheduled.
    Example: "08:00 (x) • Neville (duo)"
    """
    t = (time_str or "").strip()
    name = (client_name or "").strip()
    s_type = (session_type or "single").strip()
    st = (status or "").strip().lower()
    mark = " (x)" if st == "rescheduled" else ""
    return f"{t}{mark} • {name} ({s_type})"


def _rebuild_summary_from_sessions(sessions: list) -> str:
    """
    Rebuilds a multi-line summary from a list of session dicts:
    [{date, start_time, client_name, wa_number, session_type, status, notes}]
    Always applies the "(x)" for rescheduled items.
    Sorted by start_time ascending where possible.
    """
    if not isinstance(sessions, list) or not sessions:
        return ""
    # Sort defensively on start_time (if present)
    def _key(s):
        t = str(s.get("start_time") or "")
        # Normalise HH:MM / 08h00 etc. Keep lexicographic fallback.
        t_norm = t.replace("h", ":")
        return t_norm
    lines = []
    for s in sorted(sessions, key=_key):
        line = _fmt_line(
            time_str=str(s.get("start_time") or ""),
            client_name=str(s.get("client_name") or ""),
            session_type=str(s.get("session_type") or "single"),
            status=str(s.get("status") or "")
        )
        lines.append(line)
    return "\n".join(lines)


def _call_gas(action: str, wa_number: str | None) -> dict:
    """
    Post to GAS export endpoint and return JSON or error envelope.
    """
    if not GAS_WEBHOOK_URL:
        return {"ok": False, "error": "GAS_WEBHOOK_URL not configured"}
    payload = {"action": action}
    if wa_number:
        payload["wa_number"] = str(wa_number).strip()
    try:
        r = requests.post(GAS_WEBHOOK_URL, json=payload, timeout=REQUEST_TIMEOUT)
        if not r.ok:
            return {"ok": False, "error": f"GAS HTTP {r.status_code}", "raw": r.text}
        return r.json()
    except Exception as e:
        log.error(f"[admin_exports] GAS call failed: {e}")
        return {"ok": False, "error": str(e)}


def _standardise_export(gas_json: dict) -> dict:
    """
    Ensure response contains a `summary` with (x) markers and pass through sessions.
    If GAS already included a summary, we prefer rebuilding from `sessions`
    to guarantee the standard notation, falling back to GAS summary if needed.
    """
    if not isinstance(gas_json, dict):
        return {"ok": False, "error": "Invalid GAS response"}

    sessions = gas_json.get("sessions") or []
    if sessions:
        summary = _rebuild_summary_from_sessions(sessions)
    else:
        # Fallback to GAS-provided summary (may already have (x), but not guaranteed)
        summary = str(gas_json.get("summary") or "").strip()

    return {
        "ok": True if (sessions or summary) else False,
        "count": len(sessions) if isinstance(sessions, list) else 0,
        "summary": summary,
        "sessions": sessions,  # pass-through raw rows for consumers
    }


@bp.route("/export/today", methods=["POST"])
def export_today():
    """
    Request shape: { wa_number?: "27..." }
    Calls GAS action=export_sessions_today and standardises summary with (x).
    """
    data = request.get_json(force=True) or {}
    wa = (data.get("wa_number") or "").strip() or None
    gas = _call_gas("export_sessions_today", wa)
    std = _standardise_export(gas)
    return jsonify(std), (200 if std.get("ok") else 502)


@bp.route("/export/week", methods=["POST"])
def export_week():
    """
    Request shape: { wa_number?: "27..." }
    Calls GAS action=export_sessions_week and standardises summary with (x).
    """
    data = request.get_json(force=True) or {}
    wa = (data.get("wa_number") or "").strip() or None
    gas = _call_gas("export_sessions_week", wa)
    std = _standardise_export(gas)
    return jsonify(std), (200 if std.get("ok") else 502)


@bp.route("/health", methods=["GET"])
@bp.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "admin_exports_router",
        "requires": bool(GAS_WEBHOOK_URL),
        "timeout": REQUEST_TIMEOUT
    }), 200
