# app/diag.py
from __future__ import annotations
import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Dict

from flask import Blueprint, jsonify, request, Response
from sqlalchemy import text

from .db import db_session
from . import utils
from .invoices import (
    generate_invoice_text,
    generate_invoice_html,
    classify_type,
    rate_for_capacity,
    parse_month_spec,
)

log = logging.getLogger(__name__)
diag_bp = Blueprint("diag", __name__)

# ──────────────────────────────────────────────────────────────────────────────
# In-memory observability
# ──────────────────────────────────────────────────────────────────────────────
ERROR_COUNTERS: Dict[str, int] = {}
LAST_RUN: Dict[str, str] = {}

def note_error(kind: str) -> None:
    ERROR_COUNTERS[kind] = ERROR_COUNTERS.get(kind, 0) + 1

def note_run(job: str, when_utc: datetime | None = None) -> None:
    ts = (when_utc or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
    LAST_RUN[job] = ts

# ──────────────────────────────────────────────────────────────────────────────
# Basic diagnostics
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/")
def index():
    return "ok"

@diag_bp.get("/diag/db-test")
def db_test():
    try:
        with db_session() as s:
            res = s.execute(text("SELECT 1")).scalar_one()
        return jsonify({"ok": True, "result": int(res)})
    except Exception:
        log.exception("db-test failed")
        return jsonify({"ok": False}), 500

@diag_bp.get("/diag/cron-status")
def cron_status():
    return jsonify({
        "ok": True,
        "server_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "last_run": LAST_RUN,
        "error_counters": ERROR_COUNTERS,
    })

# ──────────────────────────────────────────────────────────────────────────────
# Template smoke tests
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.post("/diag/test-client-template")
def test_client_template():
    to = request.args.get("to", "").strip()
    hhmm = request.args.get("time", "09:00")
    for lang in ("en", "en_US"):
        resp, status = utils.send_whatsapp_template(
            to=to,
            template_name="session_tomorrow",
            lang=lang,
            components=[{"type": "body", "parameters": [{"type": "text", "text": hhmm}]}],
        )
        logging.info("[tpl-send] to=%s tpl=%s lang=%s status=%s ok=%s",
                     to, "session_tomorrow", lang, status, 200 <= status < 300)
        if 200 <= status < 300:
            return jsonify({
                "ok": True, "status_code": status, "response": resp,
                "to": to, "template": "session_tomorrow", "lang": lang
            })
    return jsonify({"ok": False, "status_code": status, "response": resp, "to": to, "lang": "en"}), 500

@diag_bp.post("/diag/test-weekly-template")
def test_weekly_template():
    to = request.args.get("to", "").strip()
    name = request.args.get("name", "Client").strip()
    items_raw = request.args.get("items", "")
    items_list = [x.strip() for x in items_raw.split(";") if x.strip()]
    items_joined = " \u2022 ".join(items_list)

    components = [{
        "type": "body",
        "parameters": [
            {"type": "text", "text": name},
            {"type": "text", "text": items_joined},
        ]
    }]

    resp, status = utils.send_whatsapp_template(
        to=to, template_name="weekly_template_message", lang="en", components=components
    )
    ok = 200 <= status < 300
    logging.info("[tpl-send] to=%s tpl=%s lang=%s status=%s ok=%s",
                 to, "weekly_template_message", "en", status, ok)
    return (jsonify({
        "ok": ok, "status_code": status, "response": resp,
        "to": to, "template": "weekly_template_message",
        "lang": "en", "vars": {"name": name, "items": items_joined}
    }), 200 if ok else 500)

# ──────────────────────────────────────────────────────────────────────────────
# Demo data seeding
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.post("/diag/seed-demo")
def seed_demo():
    try:
        wa = request.args.get("wa", "").strip()
        name = request.args.get("name", "Guest").strip()
        t1 = request.args.get("t1", "09:00").strip()
        t2 = request.args.get("t2", "07:00").strip()

        tom = date.today() + timedelta(days=1)
        day2 = tom + timedelta(days=1)

        with db_session() as s:
            c = s.execute(text("""
                SELECT id, name, wa_number FROM clients WHERE wa_number = :wa LIMIT 1
            """), {"wa": wa}).mappings().first()
            if c is None:
                c = s.execute(text("""
                    INSERT INTO clients (name, wa_number) VALUES (:name, :wa)
                    RETURNING id, name, wa_number
                """), {"name": name, "wa": wa}).mappings().first()

            def ensure_session(d: date, hhmm: str) -> int:
                sid = s.execute(text("""
                    SELECT id FROM sessions
                    WHERE session_date = :d AND start_time = :t
                    LIMIT 1
                """), {"d": d, "t": hhmm}).scalar()
                if not sid:
                    sid = s.execute(text("""
                        INSERT INTO sessions (session_date, start_time, capacity, booked_count, status)
                        VALUES (:d, :t, :cap, 0, 'scheduled')
                        RETURNING id
                    """), {"d": d, "t": hhmm, "cap": 6}).scalar()
                return int(sid)

            sid1 = ensure_session(tom, t1)
            sid2 = ensure_session(day2, t2)

            for sid in (sid1, sid2):
                exists = s.execute(text("""
                    SELECT 1 FROM bookings WHERE session_id = :sid AND client_id = :cid LIMIT 1
                """), {"sid": sid, "cid": c["id"]}).scalar()
                if not exists:
                    s.execute(text("""
                        INSERT INTO bookings (session_id, client_id, status)
                        VALUES (:sid, :cid, 'confirmed')
                    """), {"sid": sid, "cid": c["id"]})
                    s.execute(text("""
                        UPDATE sessions SET booked_count = COALESCE(booked_count,0) + 1 WHERE id = :sid
                    """), {"sid": sid})

        return jsonify({
            "ok": True,
            "client": {"id": c["id"], "name": c["name"], "wa_number": c["wa_number"]},
            "sessions_created": [{"id": int(sid1), "date": str(tom), "time": t1},
                                 {"id": int(sid2), "date": str(day2), "time": t2}],
            "bookings": [{"session_id": int(sid1), "status": "confirmed"},
                         {"session_id": int(sid2), "status": "confirmed"}]
        })
    except Exception:
        log.exception("seed_demo failed")
        return jsonify({"ok": False, "error": "seed failed"}), 500

# ──────────────────────────────────────────────────────────────────────────────
# Weekly dry run
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/diag/weekly-dry-run")
def weekly_dry_run():
    days = int(request.args.get("days", "7"))
    status_in = request.args.get("status_in", "confirmed")
    include_null_wa = request.args.get("include_null_wa", "0") in ("1", "true", "True")

    start_d = date.today()
    end_d = start_d + timedelta(days=days)

    status_tokens = [x.strip() for x in status_in.split(",") if x.strip()]
    if not status_tokens:
        status_tokens = ["confirmed"]

    sql = f"""
    SELECT c.id as client_id, c.name as client_name, c.wa_number,
           s.session_date, s.start_time, b.status as booking_status
    FROM bookings b
    JOIN sessions s ON s.id = b.session_id
    JOIN clients  c ON c.id = b.client_id
    WHERE b.status = ANY(:status_in)
      AND s.session_date >= :start_d
      AND s.session_date <  :end_d
      {"AND c.wa_number IS NOT NULL" if not include_null_wa else ""}
    ORDER BY s.session_date, s.start_time
    """
    with db_session() as s:
        rows = s.execute(text(sql), {
            "status_in": status_tokens,
            "start_d": start_d,
            "end_d": end_d,
        }).mappings().all()

    sample = []
    sendable = 0
    skip_wa = 0
    for r in rows[:100]:
        would_send = r["wa_number"] is not None
        sendable += 1 if would_send else 0
        skip_wa += 0 if would_send else 1
        sample.append({
            "client_id": r["client_id"],
            "client_name": r["client_name"],
            "wa_number": r["wa_number"],
            "session_date": str(r["session_date"]),
            "start_time": str(r["start_time"]),
            "booking_status": r["booking_status"],
            "would_send": would_send
        })

    return jsonify({
        "ok": True,
        "window_days": days,
        "status_in": status_tokens,
        "include_null_wa": include_null_wa,
        "total_matches": len(rows),
        "with_wa_number": sendable,
        "without_wa_number": skip_wa,
        "sample_first_100": sample,
    })

# ──────────────────────────────────────────────────────────────────────────────
# Invoice: text, CSV, and HTML (NEW)
# ──────────────────────────────────────────────────────────────────────────────

@diag_bp.get("/diag/invoice")
def diag_invoice_text():
    client = request.args.get("client", "").strip()
    month = request.args.get("month", "").strip() or "this month"
    if not client:
        return Response("Please provide ?client=Name", status=400, mimetype="text/plain")
    try:
        body = generate_invoice_text(client, month)
        return Response(body, mimetype="text/plain")
    except Exception:
        log.exception("invoice-text failed client=%s month=%s", client, month)
        return Response("Failed to build invoice", status=500, mimetype="text/plain")

@diag_bp.get("/diag/invoice-csv")
def diag_invoice_csv():
    client = request.args.get("client", "").strip()
    month = request.args.get("month", "").strip()
    if not client or not month:
        return Response("Use ?client=Name&month=sept", status=400, mimetype="text/plain")

    start_d, end_d, label = parse_month_spec(month)
    sql = text("""
        SELECT s.session_date, s.start_time, s.capacity, b.status
        FROM bookings b
        JOIN sessions s ON s.id = b.session_id
        JOIN clients  c ON c.id = b.client_id
        WHERE c.name ILIKE :client_name
          AND b.status IN ('confirmed', 'cancelled')
          AND s.session_date >= :start_d
          AND s.session_date <  :end_d
        ORDER BY s.session_date, s.start_time
    """)
    with db_session() as s:
        rows = s.execute(sql, {
            "client_name": f"%{client}%",
            "start_d": start_d,
            "end_d": end_d,
        }).all()

    out = io.StringIO()
    w = csv.writer(out)
    # removed capacity column
    w.writerow(["date", "time", "type", "rate", "status"])
    for d, t, cap, st in rows:
        capi = int(cap or 1)
        typ = classify_type(capi)
        rate = rate_for_capacity(capi)
        hhmm = t if isinstance(t, str) else f"{t.hour:02d}:{t.minute:02d}"
        w.writerow([str(d), hhmm, typ, rate, st])

    csv_bytes = out.getvalue().encode("utf-8")
    filename = f"invoice_{client.replace(' ', '_')}_{label.replace(' ', '_')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(csv_bytes, mimetype="text/csv", headers=headers)


@diag_bp.get("/diag/invoice-html")
def diag_invoice_html():
    """
    Printer/PDF-friendly HTML invoice.
    Example:
      /diag/invoice-html?client=Michael%20Jackson&month=sept
      /diag/invoice-html?client=Michael%20Jackson&month=2025-09
      /diag/invoice-html?client=Michael%20Jackson&month=this%20month
    """
    client = request.args.get("client", "").strip()
    month = request.args.get("month", "").strip() or "this month"
    if not client:
        return Response("<p>Please provide ?client=Name</p>", status=400, mimetype="text/html")
    try:
        html = generate_invoice_html(client, month)
        return Response(html, mimetype="text/html")
    except Exception:
        log.exception("invoice-html failed client=%s month=%s", client, month)
        return Response("<p>Failed to build invoice</p>", status=500, mimetype="text/html")
