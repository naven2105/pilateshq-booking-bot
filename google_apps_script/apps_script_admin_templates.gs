/** apps_script_admin_templates.gs
/**
 * PilatesHQ — Admin Template Notifications (06h00 + 20h00)
 * --------------------------------------------------------
 * Templates used:
 *  - admin_morning_us → "🌅 Morning Brief – Total sessions today: {{1}}. Schedule: {{2}}"
 *  - admin_20h00_us   → "🌙 Evening Preview – Tomorrow has {{1}} sessions booked. Schedule: {{2}}. Sleep well! 💤"
 *
 * Optional DEV log enabled if USE_DEV_MODE = true
 */

const CONFIG_ADMIN = (() => {
  const P = PropertiesService.getScriptProperties();
  return {
    TOKEN: P.getProperty("META_ACCESS_TOKEN"),
    PHONE_NUMBER_ID: P.getProperty("PHONE_NUMBER_ID"),
    CALENDAR_ID: P.getProperty("CALENDAR_ID"),
    ADMIN_LIVE: P.getProperty("ADMIN_LIVE"),   // Nadine (27843131635)
    ADMIN_TEST: P.getProperty("ADMIN_TEST"),   // Test (27627597357)
    USE_TEST_ADMIN: true,                      // set false when live
    USE_DEV_MODE: P.getProperty("USE_DEV_MODE") === "true",
  };
})();

/* ── Utility functions ─────────────────────────────────────── */
function formatZA(date, pattern) {
  return Utilities.formatDate(date, "Africa/Johannesburg", pattern);
}

function getCalendarEvents(start, end) {
  const cal = CalendarApp.getCalendarById(CONFIG_ADMIN.CALENDAR_ID);
  if (!cal) throw new Error("❌ Calendar not found — check CALENDAR_ID");
  return cal.getEvents(start, end).sort((a, b) => a.getStartTime() - b.getStartTime());
}

function buildScheduleText(events) {
  if (!events.length) return "No sessions booked.";
  return events.map(e => {
    const title = e.getTitle() || "";
    const [nameRaw, typeRaw] = title.split(/–|-/);
    const name = (nameRaw || "").trim();
    const type = (typeRaw || "").trim();
    const time = formatZA(e.getStartTime(), "HH:mm");
    return `${time} — ${name}${type ? ` (${type})` : ""}`;
  }).join("\n");
}

/* ── Core Template Sender ─────────────────────────────────── */
function sendTemplateAdmin(toE164, templateName, params = []) {
  const url = `https://graph.facebook.com/v19.0/${CONFIG_ADMIN.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: toE164,
    type: "template",
    template: {
      name: templateName,
      language: { code: "en_US" },
      components: [
        { type: "body", parameters: params.map(t => ({ type: "text", text: String(t) })) }
      ]
    }
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_ADMIN.TOKEN}` },
    muteHttpExceptions: true,
  };
  const res = UrlFetchApp.fetch(url, options);
  Logger.log(`📤 ${templateName} → ${toE164} (${res.getResponseCode()})`);
}

/* ── Dev Log (only runs if USE_DEV_MODE = true) ─────────────── */
function sendDevLog(message) {
  if (!CONFIG_ADMIN.USE_DEV_MODE) return; // silent in production
  const url = `https://graph.facebook.com/v19.0/${CONFIG_ADMIN.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: CONFIG_ADMIN.ADMIN_TEST,
    type: "text",
    text: { body: `✅ PilatesHQ Dev Log\n${message}` },
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_ADMIN.TOKEN}` },
  };
  try {
    UrlFetchApp.fetch(url, options);
    Logger.log(`📤 Sent dev log to ${CONFIG_ADMIN.ADMIN_TEST}`);
  } catch (e) {
    Logger.log(`❌ Dev log send failed: ${e}`);
  }
}

/* ── Jobs ──────────────────────────────────────────────────── */

/** 06h00 – Morning Brief: Today’s sessions */
function job_adminMorning_tpl() {
  const admin = CONFIG_ADMIN.USE_TEST_ADMIN ? CONFIG_ADMIN.ADMIN_TEST : CONFIG_ADMIN.ADMIN_LIVE;
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const events = getCalendarEvents(today, tomorrow);

  const total = events.length;
  const schedule = buildScheduleText(events);
  sendTemplateAdmin(admin, "admin_morning_us", [String(total), schedule]);

  // dev log confirmation
  sendDevLog(`🌅 Morning job ran successfully.\nSessions today: ${total}`);
}

/** 20h00 – Evening Preview: Tomorrow’s sessions */
function job_adminEvening_tpl() {
  const admin = CONFIG_ADMIN.USE_TEST_ADMIN ? CONFIG_ADMIN.ADMIN_TEST : CONFIG_ADMIN.ADMIN_LIVE;
  const now = new Date();
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const nextDay = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2);
  const events = getCalendarEvents(tomorrow, nextDay);

  const total = events.length;
  const schedule = buildScheduleText(events);
  sendTemplateAdmin(admin, "admin_20h00_us", [String(total), schedule]);

  // dev log confirmation
  sendDevLog(`🌙 Evening job ran successfully.\nTomorrow’s sessions: ${total}`);
}

/* ── Trigger installers ─────────────────────────────────────── */
function install_adminMorning06h_tpl() {
  ScriptApp.newTrigger("job_adminMorning_tpl").timeBased().atHour(6).everyDays(1).create();
}
function install_adminEvening20h_tpl() {
  ScriptApp.newTrigger("job_adminEvening_tpl").timeBased().atHour(20).everyDays(1).create();
}

/* ── Manual test helpers ───────────────────────────────────── */
function test_adminMorning_tpl() { job_adminMorning_tpl(); }
function test_adminEvening_tpl() { job_adminEvening_tpl(); }
