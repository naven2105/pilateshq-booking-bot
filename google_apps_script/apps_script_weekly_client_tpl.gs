/*apps_script_weekly_client_tpl.gs*/
/**
 * PilatesHQ — Weekly Client Schedule (Sunday 20h00)
 * -------------------------------------------------
 * Template: client_weekly_schedule_us
 * Sends personalised schedules to all clients every Sunday 20h00.
 * Includes "no sessions" friendly version for engagement.
 * 
 * Dev logs are enabled when USE_DEV_MODE = true
 */

const CONFIG_WEEKLY = (() => {
  const P = PropertiesService.getScriptProperties();
  return {
    TOKEN: P.getProperty("META_ACCESS_TOKEN"),
    PHONE_NUMBER_ID: P.getProperty("PHONE_NUMBER_ID"),
    CALENDAR_ID: P.getProperty("CALENDAR_ID"),
    CLIENT_SHEET_ID: P.getProperty("CLIENT_SHEET_ID"),
    USE_DEV_MODE: P.getProperty("USE_DEV_MODE") === "true",
    ADMIN_TEST: P.getProperty("ADMIN_TEST"),
  };
})();

/* ─── Utility Functions ─────────────────────────────────────────── */
function formatZAWeekly(date, pattern) {
  return Utilities.formatDate(date, "Africa/Johannesburg", pattern);
}

function getCalendarEventsRange(start, end) {
  const cal = CalendarApp.getCalendarById(CONFIG_WEEKLY.CALENDAR_ID);
  if (!cal) throw new Error("❌ Calendar not found. Check CALENDAR_ID.");
  return cal.getEvents(start, end);
}

function getAllClientsFromSheet() {
  const ss = SpreadsheetApp.openById(CONFIG_WEEKLY.CLIENT_SHEET_ID);
  const sh = ss.getSheetByName("PilatesHQ Clients") || ss.getSheets()[0];
  const rows = sh.getDataRange().getValues();
  const clients = [];
  for (let i = 1; i < rows.length; i++) {
    const name = String(rows[i][0] ?? "").trim();
    const phone = String(rows[i][1] ?? "").replace(/\D/g, "");
    if (name && phone) clients.push({ name, phone });
  }
  return clients;
}

function sendTemplateWeekly(toE164, name, scheduleSummary) {
  const url = `https://graph.facebook.com/v19.0/${CONFIG_WEEKLY.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: toE164,
    type: "template",
    template: {
      name: "client_weekly_schedule_us",
      language: { code: "en_US" },
      components: [
        {
          type: "body",
          parameters: [
            { type: "text", text: name },
            { type: "text", text: scheduleSummary },
          ],
        },
      ],
    },
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_WEEKLY.TOKEN}` },
    muteHttpExceptions: true,
  };
  const res = UrlFetchApp.fetch(url, options);
  Logger.log(`📤 client_weekly_schedule_us → ${toE164} (${res.getResponseCode()})`);
}

/* ─── Dev Log (only runs if USE_DEV_MODE = true) ───────────────── */
function sendWeeklyDevLog(message) {
  if (!CONFIG_WEEKLY.USE_DEV_MODE) return;
  const url = `https://graph.facebook.com/v19.0/${CONFIG_WEEKLY.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: CONFIG_WEEKLY.ADMIN_TEST,
    type: "text",
    text: { body: `✅ PilatesHQ Dev Log\n${message}` },
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_WEEKLY.TOKEN}` },
  };
  try {
    UrlFetchApp.fetch(url, options);
    Logger.log(`📤 Sent weekly dev log to ${CONFIG_WEEKLY.ADMIN_TEST}`);
  } catch (e) {
    Logger.log(`❌ Weekly dev log send failed: ${e}`);
  }
}

/* ─── Weekly Job ───────────────────────────────────────────────── */
function job_clientWeeklySchedule_tpl() {
  const now = new Date();
  // upcoming week: Monday → Sunday
  const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() + (1 - now.getDay()) + 1); // Monday
  const weekEnd = new Date(weekStart.getTime() + 7 * 24 * 60 * 60 * 1000); // next Monday
  const events = getCalendarEventsRange(weekStart, weekEnd);

  // group events by client
  const scheduleMap = {};
  events.forEach(ev => {
    const title = ev.getTitle() || "";
    const [nameRaw] = title.split(/–|-/);
    const name = (nameRaw || "").trim();
    if (!name) return;

    const day = formatZAWeekly(ev.getStartTime(), "EEE d MMM");
    const time = formatZAWeekly(ev.getStartTime(), "HH:mm");
    const slot = `${day} ${time}`;
    if (!scheduleMap[name]) scheduleMap[name] = [];
    scheduleMap[name].push(slot);
  });

  const clients = getAllClientsFromSheet();
  let withSessions = 0;
  let withoutSessions = 0;

  clients.forEach(c => {
    const sessions = scheduleMap[c.name];
    const summary = sessions && sessions.length
      ? sessions.join(", ")
      : "No sessions booked this week. We miss you! 💜";
    if (sessions && sessions.length) withSessions++; else withoutSessions++;
    sendTemplateWeekly(c.phone, c.name, summary);
  });

  // dev-only confirmation
  sendWeeklyDevLog(`📅 Weekly schedule sent to ${clients.length} clients\n(${withSessions} with sessions, ${withoutSessions} with none)`);
}

/* ─── Trigger Installer ───────────────────────────────────────── */
function install_clientWeeklySchedule_tpl() {
  // Sunday 20h00
  ScriptApp.newTrigger("job_clientWeeklySchedule_tpl")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.SUNDAY)
    .atHour(20)
    .create();
}

/* ─── Manual Test ─────────────────────────────────────────────── */
function test_clientWeeklySchedule_tpl() { job_clientWeeklySchedule_tpl(); }
