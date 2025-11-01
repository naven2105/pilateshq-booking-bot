<!-- readme.md -->
# PilatesHQ — Render Backend (Flask / Meta Webhook)

This folder contains the Flask backend that powers the PilatesHQ Booking Bot — handling real-time WhatsApp automation and secure integrations with Google Apps Script.

---

## 🧭 Overview

The Render server remains online to process instant WhatsApp events and bridge them to Google Apps Script (GAS) for persistent automation and reporting.

### Real-time actions handled here
- Client onboarding & registration  
- Session bookings and reschedules  
- NLP message parsing (e.g. “Reschedule Mary Smith”)  
- Secure invoice generation & dual-channel delivery (WhatsApp + Email)  
- Payment logging & invoice matching  
- Admin notifications, summaries, and insights  
- Forwarding structured events to GAS for storage and dashboards  

⏰ All scheduled jobs (daily reminders, weekly summaries, auto-billing) run entirely inside Google Apps Script, keeping Render always-on but low-cost.

---

## 🗂️ Folder Structure (Phase 17)

| File | Purpose |
|------|----------|
| `app/__init__.py` | Registers all Flask blueprints — unified architecture (v1.7.0) |
| `app/router_webhook.py` | Core WhatsApp Cloud API event listener |
| `app/tasks_router.py` | GAS-triggered reminders (morning / evening / week-ahead / birthdays) |
| `app/tasks_sheets.py` | Shared Google Sheets read/write utilities |
| `app/client_reminders.py` | Sends Meta-approved templates to clients |
| `app/package_events.py` | Handles credit usage and low-balance alerts |
| `app/invoices_router.py` | ✅ Unified Invoices + Payments — PDF generation, delivery, and logging |
| `app/schedule_router.py` | ✅ Bookings + Reschedules + Admin Digests |
| `app/dashboard_router.py` | Weekly & monthly studio insight reports |
| `app/admin_actions_router.py` | NLP admin commands (discounts, session type changes) |
| `app/standing_router.py` | Recurring slot (“standing booking”) management |
| `app/utils.py` | Shared helpers for WhatsApp messaging + GAS POST requests |
| `app/tokens.py` | Secure token encoding / decoding for invoice links |
| `app/static/pilateshq_logo.png` | Logo used in invoice PDF headers |

🗑️ **Removed / merged files**  
- `attendance_router.py` → merged into `schedule_router.py`  
- `payments_router.py` → merged into `invoices_router.py`  

---

## ⚙️ Environment Variables

| Variable | Description |
|-----------|-------------|
| META_ACCESS_TOKEN | WhatsApp Cloud API access token |
| PHONE_NUMBER_ID | PilatesHQ Business WhatsApp ID |
| GAS_INVOICE_URL | Google Apps Script endpoint for invoices & payments |
| GAS_SCHEDULE_URL | Google Apps Script endpoint for schedule automation |
| CLIENT_SHEET_ID | Google Sheet ID for client / invoice data |
| NADINE_WA | Nadine’s WhatsApp number (for admin alerts) |
| BASE_URL | Public Render URL for secure invoice token links |
| TEMPLATE_LANG | Default Meta template locale (e.g. en_US) |

*(Optional)* Gmail API credentials may still be used if direct email sending is re-enabled.

---

## 💼 Phase 17 — Unified Invoices + Payments

**Objective:** simplify billing automation by merging invoice delivery + payment logging into a single secure workflow.

### Key Features
- Auto-generate PDF invoices with studio branding and bank details.  
- Deliver each invoice via both WhatsApp and Email.  
- Tokenised link security (expiry within 48 hours).  
- Payments logged directly by Nadine through bot commands or NLP input.  
- Automatic matching of payments to open invoices (via GAS).  
- Private WhatsApp confirmation to Nadine only — no client payment messages.  
- Centralised GAS logging for auditing and dashboard analytics.

### WhatsApp Templates Used
- `client_generic_alert_us` – Client invoice delivery  
- `admin_generic_alert_us` – Admin alerts and summaries  
- `payment_logged_admin_us` – Payment confirmations (Nadine only)

---

## 🧩 System Integration Flow
Client Message → Meta Webhook → Flask (router_webhook)
└→ NLP / schedule_router / invoices_router
└→ Google Apps Script (write to Sheets, trigger logic)
└→ Sends summaries & dashboards back via /dashboard


All daily / weekly triggers (e.g. reminders, dashboards, auto-invoices) originate in Google Apps Script and POST to the corresponding Flask endpoint.

---

## 🧠 Operational Notes

- Meta Webhook URL → `/webhook`  
- GAS calls → authenticated HTTPS POST to Render endpoints  
- No CRON or APScheduler jobs run on Render  
- Backend may run on Render free tier since CPU use is minimal  
- Environment variables must be configured in Render Dashboard  

---

## 🔮 Future Simplification
Once all event logic (bookings, invoices, reschedules, payments) is fully migrated to Google Apps Script or Meta Workflows,  
this Render backend can be retired to reduce hosting costs while keeping GAS as the sole automation engine.

---

## 📘 Phase 25 — Reschedule Handling Policy

**Purpose:** Define clear, consistent rules for how reschedules are captured, logged, and reversed within the PilatesHQ Booking Bot ecosystem.

### 1️⃣ Client-Initiated Reschedules
- Triggered when client sends “reschedule”, “cancel”, “can’t make”, “cannot make”, “miss class”, or “skip today”.  
- Bot response:  
  > 💜 Got it — I’ve marked your session for rescheduling. Nadine will contact you soon.  
- GAS marks latest booked session as `Reschedule Requested (reason=client)` and notifies Nadine.

### 2️⃣ Admin-Initiated Reschedules
- Nadine commands:  
  - `reschedule {client}` → `Rescheduled (reason=admin)`  
  - `{client} noshow` → `Rescheduled (reason=noshow)`  
- Bot confirms action to Nadine in WhatsApp.

### 3️⃣ Reversals / Reactivations
- Clients cannot reverse reschedules via the bot.  
- If client changes mind, they message Nadine directly.  
- Nadine decides if space allows and manually reinstates the booking (via Sheets or admin tools).  
- This keeps reversals human-approved and prevents over-booking.

### 4️⃣ Data & Audit
- GAS records date, time, trigger source (`client | admin | noshow`), and previous session state.  
- Monthly reports can analyse reschedule frequency and reasons.

### 5️⃣ Design Principle
> All automation flows one-way — from *Active → Rescheduled*.  
> Only Nadine may reverse a reschedule manually.

---

