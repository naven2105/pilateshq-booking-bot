# PilatesHQ WhatsApp Automation System

An integrated scheduling and client-communication solution built for **PilatesHQ (Lyndhurst, South Africa)**.  
The system combines **Google Apps Script** (for automation) and **Render (Flask backend)** to deliver a cost-efficient, WhatsApp-based booking experience.

---

## 🎯 Overview

PilatesHQ manages 100+ clients and daily sessions via WhatsApp without needing laptops or expensive software.  
The solution uses Meta’s **WhatsApp Cloud API**, Google Workspace (Sheets + Calendar), and lightweight automation to:

- Send **daily reminders** (clients + admin)
- Share **weekly schedules**
- Reduce **no-shows** via next-hour reminders
- Handle **reschedule** requests
- Log all data automatically in Google Sheets

All recurring tasks run free on Google Apps Script — replacing Render’s cron jobs and databases.

---

## ⚙️ Architecture


Clients ↔ WhatsApp Cloud API ↔ Render (Flask)
│
└──▶ Google Apps Script (Automation)
├── Sheets → Client data
├── Calendar → Session schedule
├── WhatsApp API → Templates
└── Time triggers → 06h00 / 20h00 / weekly


| Component | Platform | Function |
|------------|-----------|-----------|
| WhatsApp Webhook | Render (Flask) | Handles real-time incoming messages |
| Scheduled Automations | Google Apps Script | Sends reminders, summaries, weekly schedules |
| Data Storage | Google Sheets + Calendar | Replaces PostgreSQL database |
| Cost | ± $7–10/month | Reduced from ± $42/month on Render |

---

## 🧩 Repository Structure

pilateshq-whatsapp-bot/
│
├── render_backend/ # Flask backend (real-time WhatsApp handling)
│ ├── app/
│ └── README.md
│
├── google_apps_script/ # Google Apps Script automations (free)
│ ├── Code.gs
│ ├── apps_script_admin_templates.gs
│ ├── apps_script_client_templates.gs
│ ├── apps_script_weekly_client_tpl.gs
│ ├── apps_script_healthcheck.gs
│ ├── apps_script_reschedule_logger.gs
│ └── README.md
│
├── docs/ # Optional documentation & diagrams
│ └── README.md
│
└── README.md # This file


---

## 🧠 Key Design Principles
- **Low-cost operation:** most logic runs inside Google Workspace.
- **Mobile-first:** Nadine (admin) can manage everything through WhatsApp.
- **Separation of concerns:**  
  - Render handles instant webhooks.  
  - Apps Script handles scheduled messaging.
- **Environment toggle:** `USE_DEV_MODE = true|false` controls test confirmations.
- **Scalable design:** new studios can be onboarded by duplicating the Apps Script project.

---

## 🚀 Deployment Notes
- Render app uses `.env` variables for Meta tokens and the Apps Script webhook URL.  
- Google Apps Script requires Script Properties for Meta credentials and calendar IDs.  
- Triggers run automatically:
  - `06h00` → Admin morning brief  
  - `20h00` → Admin evening preview + client reminders  
  - `Every 5 min` → Next-hour reminder  
  - `Sunday 20h00` → Weekly schedule  

---

## 💰 Cost Summary
| Service | Platform | Est. Monthly |
|----------|-----------|--------------|
| Render server (uptime only) | Render | $7 |
| Google Workspace (automation) | Google | Free |
| Meta WhatsApp Cloud API | Meta | Free Tier |
| **Total** | | **≈ $7–10** |

---

## 📜 Credits
Developed by **Naven Pather**  
Consultant: **KLResolute (Pty) Ltd** — AI, Process & Automation Solutions.  
Powered by Google Workspace + Meta WhatsApp Cloud API.

