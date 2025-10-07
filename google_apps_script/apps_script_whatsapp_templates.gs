/** apps_script_whatsapp_templates.gs
/**
 * PilatesHQ – WhatsApp Templates (simplified)
 * Uses Meta-approved templates for reliable delivery.
 */

const CONFIG = (() => {
  const P = PropertiesService.getScriptProperties();
  return {
    TOKEN: P.getProperty("META_ACCESS_TOKEN"),
    PHONE_NUMBER_ID: P.getProperty("PHONE_NUMBER_ID"),
    CALENDAR_ID: P.getProperty("CALENDAR_ID"),
    CLIENT_SHEET_ID: P.getProperty("CLIENT_SHEET_ID"),
    ADMIN_TEST: P.getProperty("ADMIN_TEST"),   // 27627597357 (admin)
    ADMIN_LIVE: P.getProperty("ADMIN_LIVE"),   // Nadine
    USE_TEST_ADMIN: true                       // false when live
  };
})();

/** Generic Template Sender **/
function sendTemplate(toE164, templateName, params = [], lang = "en_US") {
  const url = `https://graph.facebook.com/v19.0/${CONFIG.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: toE164,
    type: "template",
    template: {
      name: templateName,
      language: { code: lang },
      components: [
        { type: "body", parameters: params.map(t => ({ type: "text", text: t })) }
      ]
    }
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG.TOKEN}` },
  };
  const res = UrlFetchApp.fetch(url, options);
  Logger.log(`📤 ${templateName} → ${toE164} (${res.getResponseCode()})`);
}

/** Look up phone in Sheet **/
function getPhone(name) {
  const ss = SpreadsheetApp.openById(CONFIG.CLIENT_SHEET_ID);
  const sh = ss.getSheetByName("PilatesHQ Clients");
  const data = sh.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if ((data[i][0] + "").trim().toLowerCase() === name.trim().toLowerCase())
      return (data[i][1] + "").trim();
  }
  return null;
}

/** Morning admin summary – TEMPLATE: admin_morning_us **/
function job_adminMorning_tpl() {
  const admin = CONFIG.USE_TEST_ADMIN ? CONFIG.ADMIN_TEST : CONFIG.ADMIN_LIVE;
  const cal = CalendarApp.getCalendarById(CONFIG.CALENDAR_ID);
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const events = cal.getEvents(today, tomorrow);
  const lines = events.map(e => {
    const t = e.getTitle();
    const [n, type] = t.split(/–|-/);
    return `${Utilities.formatDate(e.getStartTime(), "Africa/Johannesburg", "HH:mm")} — ${n.trim()} (${(type||"session").trim()})`;
  });
  sendTemplate(admin, "admin_morning_us", [String(events.length), lines.join("; ") || "No sessions"]);
}

/** Tomorrow client reminders – TEMPLATE: client_session_tomorrow_us **/
function job_clientTomorrow_tpl() {
  const cal = CalendarApp.getCalendarById(CONFIG.CALENDAR_ID);
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2);
  const events = cal.getEvents(start, end);
  events.forEach(e => {
    const [n] = (e.getTitle() || "").split(/–|-/);
    const phone = getPhone(n.trim());
    if (phone) sendTemplate(phone, "client_session_tomorrow_us",
       [Utilities.formatDate(e.getStartTime(), "Africa/Johannesburg", "HH:mm")]);
  });
}

/** Install once for daily automation **/
function install_tplTriggers() {
  ScriptApp.newTrigger("job_adminMorning_tpl").timeBased().atHour(6).everyDays(1).create();
  ScriptApp.newTrigger("job_clientTomorrow_tpl").timeBased().atHour(20).everyDays(1).create();
}

/** Manual tests **/
function test_admin_tpl() { job_adminMorning_tpl(); }
function test_client_tpl() { job_clientTomorrow_tpl(); }
