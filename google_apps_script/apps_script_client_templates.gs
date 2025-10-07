/** apps_script_client_templates.gs
 * 
 * PilatesHQ — Client Template Reminders (Meta Cloud API)
 * ------------------------------------------------------
 * Templates used:
 *  - client_session_tomorrow_us  {{1}} = time (HH:mm)
 *  - client_session_next_hour_us {{1}} = time (HH:mm)
 * 
 * Dev-mode flag allows optional WhatsApp confirmation logs.
 */

const CONFIG_TPL = (() => {
  const P = PropertiesService.getScriptProperties();
  return {
    TOKEN: P.getProperty("META_ACCESS_TOKEN"),
    PHONE_NUMBER_ID: P.getProperty("PHONE_NUMBER_ID"),
    CALENDAR_ID: P.getProperty("CALENDAR_ID"),
    CLIENT_SHEET_ID: P.getProperty("CLIENT_SHEET_ID"),
    USE_DEV_MODE: P.getProperty("USE_DEV_MODE") === "true",
    ADMIN_TEST: P.getProperty("ADMIN_TEST"), // for dev logs
  };
})();

/* ── Utility Functions ─────────────────────────────────────── */
function zaTime(d) { return Utilities.formatDate(d, "Africa/Johannesburg", "HH:mm"); }
function getCalendarTPL() {
  const cal = CalendarApp.getCalendarById(CONFIG_TPL.CALENDAR_ID);
  if (!cal) throw new Error("Calendar not found. Check CALENDAR_ID.");
  return cal;
}
function getPhoneByNameTPL(name) {
  const ss = SpreadsheetApp.openById(CONFIG_TPL.CLIENT_SHEET_ID);
  const sh = ss.getSheetByName("PilatesHQ Clients") || ss.getSheets()[0];
  const rows = sh.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    const n = String(rows[i][0] ?? "").trim().toLowerCase();
    if (n && n === String(name ?? "").trim().toLowerCase()) {
      return String(rows[i][1] ?? "").replace(/\D/g, "");
    }
  }
  return null;
}

/* ── Dev Log (only active when USE_DEV_MODE = true) ─────────── */
function sendClientDevLog(message) {
  if (!CONFIG_TPL.USE_DEV_MODE) return;
  const url = `https://graph.facebook.com/v19.0/${CONFIG_TPL.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: CONFIG_TPL.ADMIN_TEST,
    type: "text",
    text: { body: `✅ PilatesHQ Dev Log\n${message}` },
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_TPL.TOKEN}` },
  };
  try {
    UrlFetchApp.fetch(url, options);
    Logger.log(`📤 Dev log sent → ${CONFIG_TPL.ADMIN_TEST}`);
  } catch (e) {
    Logger.log(`❌ Dev log failed: ${e}`);
  }
}

/* ── Template Sender ───────────────────────────────────────── */
function sendTemplateTPL(toE164, templateName, params = [], lang = "en_US") {
  if (!toE164) return Logger.log("⚠️ Missing recipient number.");
  const url = `https://graph.facebook.com/v19.0/${CONFIG_TPL.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: toE164,
    type: "template",
    template: {
      name: templateName,
      language: { code: lang },
      components: [
        { type: "body", parameters: params.map(t => ({ type: "text", text: String(t) })) }
      ]
    }
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_TPL.TOKEN}` },
    muteHttpExceptions: true,
  };
  const res = UrlFetchApp.fetch(url, options);
  Logger.log(`📤 ${templateName} → ${toE164} (${res.getResponseCode()})`);
}

/* ── Jobs ───────────────────────────────────────────────────── */

/** 20h00 — Tomorrow reminders */
function job_clientTomorrow_tpl() {
  const cal = getCalendarTPL();
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const end   = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2);
  const events = cal.getEvents(start, end);

  let sentCount = 0;
  events.forEach(ev => {
    const title = ev.getTitle() || "";
    const [nameRaw] = title.split(/–|-/);
    const clientName = (nameRaw || "").trim();
    if (!clientName) return;

    const phone = getPhoneByNameTPL(clientName);
    if (!phone) return Logger.log(`⚠️ No phone for ${clientName}`);

    const timeParam = zaTime(ev.getStartTime());
    sendTemplateTPL(phone, "client_session_tomorrow_us", [timeParam], "en_US");
    sentCount++;
  });

  // dev-only log
  sendClientDevLog(`🌙 Client tomorrow reminders sent: ${sentCount}`);
}

/** Every 5 min — sessions starting within next hour */
function job_clientNextHour_tpl() {
  const cal = getCalendarTPL();
  const now = new Date();
  const inHour = new Date(now.getTime() + 60 * 60 * 1000);
  const events = cal.getEvents(now, inHour);

  let sentCount = 0;
  events.forEach(ev => {
    const start = ev.getStartTime();
    if (start <= now) return;
    const title = ev.getTitle() || "";
    const [nameRaw] = title.split(/–|-/);
    const clientName = (nameRaw || "").trim();
    if (!clientName) return;

    const phone = getPhoneByNameTPL(clientName);
    if (!phone) return Logger.log(`⚠️ No phone for ${clientName}`);

    sendTemplateTPL(phone, "client_session_next_hour_us", [zaTime(start)], "en_US");
    sentCount++;
  });

  // dev-only log
  sendClientDevLog(`⏰ Client next-hour reminders sent: ${sentCount}`);
}

/* ── Trigger Installers ─────────────────────────────────────── */
function install_clientTomorrow_20h_tpl() {
  ScriptApp.newTrigger("job_clientTomorrow_tpl").timeBased().atHour(20).everyDays(1).create();
}
function install_clientNextHour_5min_tpl() {
  ScriptApp.newTrigger("job_clientNextHour_tpl").timeBased().everyMinutes(5).create();
}

/* ── Manual Tests ───────────────────────────────────────────── */
function test_clientTomorrow_tpl() { job_clientTomorrow_tpl(); }
function test_clientNextHour_tpl() { job_clientNextHour_tpl(); }
