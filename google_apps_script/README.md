# PilatesHQ — Google Apps Script Automation

This folder contains all Apps Script code that replaces the costly Render cron and database functions.  
These scripts connect directly to Google Sheets, Calendar, and Meta's WhatsApp Cloud API.

## Files Overview
| File | Purpose |
|------|----------|
| `Code.gs` | Main scheduler logic, daily jobs (06h00 + 20h00) |
| `apps_script_admin_templates.gs` | Sends admin morning + evening template messages |
| `apps_script_client_templates.gs` | Sends client night-before + next-hour template reminders |
| `apps_script_weekly_client_tpl.gs` | Sends weekly client schedules every Sunday |
| `apps_script_healthcheck.gs` | Dev-mode job confirmation logs |
| `apps_script_reschedule_logger.gs` | Logs and alerts Nadine when clients request “RESCHEDULE” |

## Notes
- All triggers are time-based and free under Google Workspace.
- Switch `USE_DEV_MODE` in Script Properties to control dev logs.
- The Meta API credentials (`META_ACCESS_TOKEN`, `PHONE_NUMBER_ID`) must be set in Script Properties.
