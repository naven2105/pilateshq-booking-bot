/**code.gs */
/**
 * PilatesHQ WhatsApp Scheduler — Combined version
 * -----------------------------------------------
 * • 20h00: Client reminders (from Calendar & Sheet)
 * • 06h00: Admin summary (today’s schedule)
 */

/* ─── Utility functions ─────────────────────────────────────── */
function getClientPhone(name) {
  const ss = SpreadsheetApp.openById(CONFIG.CLIENT_SHEET_ID);
  const sh = ss.getSheetByName("PilatesHQ Clients");
  const data = sh.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if ((data[i][0] + "").trim().toLowerCase() === name.trim().toLowerCase()) {
      return (data[i][1] + "").trim();
    }
  }
  return null;
}

function sendWhatsAppText(to, body) {
  if (!to) return Logger.log("⚠️ Missing recipient number.");
  const url = `https://graph.facebook.com/v19.0/${CONFIG.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to, type: "text",
    text: { body }
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG.TOKEN}` },
  };
  try {
    const res = UrlFetchApp.fetch(url, options);
    Logger.log(`✅ Sent to ${to} (${res.getResponseCode()})`);
  } catch (e) {
    Logger.log(`❌ Send failed to ${to}: ${e}`);
  }
}

/* ─── Nightly client reminders (20h00) ───────────────────────── */
function job_nightlyClientReminders() {
  const cal = CalendarApp.getCalendarById(CONFIG.CALENDAR_ID);
  const now = new Date();
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const nextDay = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2);
  const events = cal.getEvents(tomorrow, nextDay);

  events.forEach(ev => {
    const title = ev.getTitle();
    const clientName = title.split("–")[0].trim();
    const start = Utilities.formatDate(ev.getStartTime(), "Africa/Johannesburg", "HH:mm");
    const date = Utilities.formatDate(ev.getStartTime(), "Africa/Johannesburg", "EEE d MMM");
    const phone = getClientPhone(clientName);
    if (!phone) return Logger.log(`⚠️ No phone for ${clientName}`);
    const msg = `💜 Hi ${clientName}! Reminder from PilatesHQ:\nYour session is booked for ${date} at ${start}.\nSee you soon!`;
    sendWhatsAppText(phone, msg);
  });
}

/* ─── Morning admin summary (06h00) ──────────────────────────── */
function job_morningAdminSummary() {
  const admin = CONFIG.USE_TEST_ADMIN ? CONFIG.ADMIN_TEST : CONFIG.ADMIN_LIVE;
  if (!admin) return Logger.log("⚠️ No admin recipient.");
  const cal = CalendarApp.getCalendarById(CONFIG.CALENDAR_ID);
  const today = new Date();
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const events = cal.getEvents(today, tomorrow);
  const lines = events
    .sort((a, b) => a.getStartTime() - b.getStartTime())
    .map(ev => {
      const title = ev.getTitle();
      const parts = title.split("–");
      const name = (parts[0] || "").trim();
      const type = (parts[1] || "").trim();
      const time = Utilities.formatDate(ev.getStartTime(), "Africa/Johannesburg", "HH:mm");
      return `${time} — ${name} (${type})`;
    });
  const header = `🌞 Good morning ${CONFIG.USE_TEST_ADMIN ? "(TEST)" : ""}!\nToday’s sessions — ${Utilities.formatDate(today, "Africa/Johannesburg", "EEE d MMM")}\n`;
  const body = lines.length ? lines.join("\n") : "No sessions booked.";
  sendWhatsAppText(admin, header + body);
}

/* ─── One-time trigger installers ────────────────────────────── */
function install_morning06h() {
  ScriptApp.newTrigger("job_morningAdminSummary")
    .timeBased().atHour(6).everyDays(1).create();
}
function install_nightly20h() {
  ScriptApp.newTrigger("job_nightlyClientReminders")
    .timeBased().atHour(20).everyDays(1).create();
}

/* ─── Manual test helpers ───────────────────────────────────── */
function test_adminSummaryNow() { job_morningAdminSummary(); }
function test_nextDayRemindersNow() { job_nightlyClientReminders(); }

function test_checkCalendarSource() {
  const id = PropertiesService.getScriptProperties().getProperty("CALENDAR_ID");
  const cal = CalendarApp.getCalendarById(id);
  const now = new Date();
  const nextWeek = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 7);
  const events = cal.getEvents(now, nextWeek);
  Logger.log(`📅 Found ${events.length} events from ${id}`);
  events.slice(0, 5).forEach(e => Logger.log(`- ${e.getTitle()}`));
}

/** ─── DAILY AUTOMATION TRIGGERS ─────────────────────────── **/

// 06h00 — morning admin summary
function install_morning06h() {
  ScriptApp.newTrigger("job_morningAdminSummary")
    .timeBased()
    .atHour(6)
    .everyDays(1)
    .create();
}

// 20h00 — evening client reminders (and optional admin preview)
function install_evening20h() {
  // client reminders
  ScriptApp.newTrigger("job_clientTomorrow_tpl")
    .timeBased()
    .atHour(20)
    .everyDays(1)
    .create();

  // optional admin preview (uncomment if needed)
  // ScriptApp.newTrigger("job_morningAdminSummary")
  //   .timeBased()
  //   .atHour(20)
  //   .everyDays(1)
  //   .create();
}

