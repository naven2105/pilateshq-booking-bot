PilatesHQ WhatsApp Bot

A modular WhatsApp chatbot built for PilatesHQ using Flask, Meta WhatsApp Cloud API, and OpenAI GPT.
It supports structured booking conversations, admin tools for Nadine, and wellness Q&A powered by ChatGPT.

🔑 Features

Clean modular design:

router_webhook.py → main webhook dispatcher

router_admin.py → admin messages, flows, buttons

router_client.py → client menu, bookings, cancellations, messaging Nadine

router_helpers.py → shared helpers (DOB parsing, client record creation)

admin_bookings.py / admin_clients.py / admin_core.py → admin logic for Nadine

client_commands.py → client booking, cancel, message Nadine

prospect.py → prospect onboarding + auto alerts

utils.py → WhatsApp Cloud API helpers (text, template, flow, buttons)

db.py → DB session helper

New client reject flow:

Clients can tap ❌ Reject to cancel a booking.

Booking is updated in DB (status = rejected).

Client is notified.

Nadine gets an admin nudge via template alert.

Ready for Render deployment (Procfile + requirements.txt included).

Securely uses environment variables for Meta + OpenAI tokens.

Supports WhatsApp Flows for structured client registration.

Admin alerts via Meta templates: Nadine receives nudges when new leads or booking changes occur.

🗂 Project Structure

├── app/
│   ├── wsgi.py               # Flask entrypoint for Render
│   ├── router.py             # Deprecated shim → imports router_webhook
│   ├── router_webhook.py     # Main webhook dispatcher
│   ├── router_admin.py       # Admin interactive / text handling
│   ├── router_client.py      # Client message handling
│   ├── router_helpers.py     # Shared helpers (DOB, client creation)
│   ├── admin_core.py         # Admin orchestration
│   ├── admin_bookings.py     # Admin booking management
│   ├── admin_clients.py      # Admin client management
│   ├── client_commands.py    # Client booking/cancel/message Nadine
│   ├── prospect.py           # Prospect onboarding → leads table
│   ├── invoices.py           # Invoice generation
│   ├── utils.py              # WhatsApp API helpers (text/template/flows)
│   ├── db.py                 # SQLAlchemy DB session helpers
│   ├── admin_nudge.py        # Sends template nudges to Nadine
│   └── admin_notify.py       # Logs & admin notifications
├── requirements.txt
├── Procfile
└── README.md

  📦 Dependencies

flask → web server

requests → send messages to Meta Cloud API

openai → GPT-based assistant

sqlalchemy + psycopg2 → database access

gunicorn → production server (Render)

🆕 Workflows
Prospect → Admin Workflow

Guest sends enquiry.

Prospect stored in leads.

Nadine receives Meta-approved template alert + “Add Client” button.

Flow opens → client details prefilled → client inserted into DB.

Admin → Client Booking Workflow

Nadine can book via text (Book John 2025-10-05 08h00 single).

System normalises time (08h00 → 08:00) and inserts session/booking.

Client receives confirmation with ❌ Reject button.

If client rejects:

Booking marked rejected.

Client receives cancellation message.

Nadine receives admin nudge.

Client → Admin Workflow

Commands supported:

bookings → upcoming sessions list.

cancel next → cancel next booking.

cancel Mon 08:00 → cancel specific booking.

message Nadine ... → forwards message to Nadine.

🔧 Environment Variables

# Meta WhatsApp
WHATSAPP_TOKEN=...
PHONE_NUMBER_ID=...

# Verification
VERIFY_TOKEN=changeme

# OpenAI
OPENAI_API_KEY=...

# Admin setup
ADMIN_WA_LIST=2782...,2773...   # Nadine’s WA numbers
NADINE_WA=2782...

# Templates
TPL_ADMIN_PROSPECT=guest_query_alert
TEMPLATE_LANG=en_US

# Flows
CLIENT_REGISTRATION_FLOW_ID=24571517685863108


📲 WhatsApp Templates

admin_new_lead_alert → Prospect → Admin nudge

client_registration → WhatsApp Flow for onboarding

admin_update_us → Generic admin update (cancel/reject/sick)

admin_20h00_us → Evening preview (tomorrow’s sessions)

admin_morning_us → Morning briefing (today’s sessions)

client_session_next_hour_us → Reminder for session in next hour

client_session_tomorrow_us → Reminder for tomorrow’s session

🚀 Deployment
Local
flask run --host=0.0.0.0 --port=5000

Render
gunicorn app.wsgi:app

  ✅ With this setup:

Guests → auto admin alert + Add Client button.

Nadine → register + book client in one workflow.

Clients → view/cancel bookings or message Nadine directly.

Rejects → auto cancel + Nadine notified.

⌨️ Quick Command Cheat Sheet
👩‍💼 Nadine (Admin Commands)

Nadine can send plain text commands to quickly manage sessions and clients:

Book a session

Book John 2025-10-05 08h00 single
Book Mary tomorrow 09h00 duo
Book Peter every Tuesday 08h00 single


➡️ Creates session + booking, notifies client with ❌ Reject button.

Cancel next session for a client

Cancel John


Mark attendance

John sick
John no-show


Other admin actions (button-driven)

Add new client via Flow

Cancel all sessions

Confirm/reject deactivation

🙋 Clients (Self-Service Commands)

Clients can message the bot directly for their own bookings:

View bookings

bookings
my bookings
sessions


Cancel next booking

cancel next
cancel upcoming


Cancel a specific booking

cancel Mon 08:00


Send Nadine a message

message Nadine I need to reschedule my Monday lesson


➡️ Forwarded directly to Nadine with client details.

Reject a booking
Tap ❌ Reject button → booking cancelled + Nadine notified.

⚡ With this cheat sheet:

Nadine has 1-line booking management.

Clients get self-service bookings.

All flows remain synced in DB + Nadine gets nudges for every important event.