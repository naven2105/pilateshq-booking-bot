/**apps_script_healthcheck.gs
/**
 * PilatesHQ — Health Check (DEV ONLY)
 * -----------------------------------
 * Sends a WhatsApp summary of daily automation runs when USE_DEV_MODE = true.
 *
 * Required Script Properties:
 *  USE_DEV_MODE = true | false
 *  META_ACCESS_TOKEN
 *  PHONE_NUMBER_ID
 *  ADMIN_TEST (your WhatsApp number)
 */

const CONFIG_ENV = (() => {
  const P = PropertiesService.getScriptProperties();
  return {
    USE_DEV_MODE: P.getProperty("USE_DEV_MODE") === "true",
    TOKEN: P.getProperty("META_ACCESS_TOKEN"),
    PHONE_NUMBER_ID: P.getProperty("PHONE_NUMBER_ID"),
    ADMIN_TEST: P.getProperty("ADMIN_TEST"), // you or Nadine
  };
})();

/* ─── Utility ─────────────────────────────────────────────── */
function sendDevLog(message) {
  if (!CONFIG_ENV.USE_DEV_MODE) return; // exit if not in dev mode
  const url = `https://graph.facebook.com/v19.0/${CONFIG_ENV.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: CONFIG_ENV.ADMIN_TEST,
    type: "text",
    text: { body: `✅ PilatesHQ Dev Log\n${message}` },
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_ENV.TOKEN}` },
  };
  try {
    UrlFetchApp.fetch(url, options);
    Logger.log(`📤 Sent dev log to ${CONFIG_ENV.ADMIN_TEST}`);
  } catch (e) {
    Logger.log(`❌ Dev log send failed: ${e}`);
  }
}

/* ─── Example job completions ─────────────────────────────── */
function logMorningSummaryComplete(totalSessions) {
  sendDevLog(`🌅 Morning job ran successfully.\nSessions today: ${totalSessions}`);
}

function logEveningSummaryComplete(totalSessions) {
  sendDevLog(`🌙 Evening job ran successfully.\nTomorrow’s sessions: ${totalSessions}`);
}

/* ─── Manual test ─────────────────────────────────────────── */
function test_devLog() {
  sendDevLog("This is a test confirmation message. System running normally.");
}
