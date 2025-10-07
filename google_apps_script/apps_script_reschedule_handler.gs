/**apps_script_reschedule_handler.gs
/**
 * PilatesHQ — "RESCHEDULE" Reply Handler
 * --------------------------------------
 * Detects incoming WhatsApp replies containing the keyword "RESCHEDULE"
 * and alerts the Admin (Nadine) automatically.
 *
 * This script runs as a Web App (Deployed as: "Execute as me", accessible by "Anyone")
 * and is connected to your Meta webhook.
 */

const CONFIG_REPLY = (() => {
  const P = PropertiesService.getScriptProperties();
  return {
    TOKEN: P.getProperty("META_ACCESS_TOKEN"),
    PHONE_NUMBER_ID: P.getProperty("PHONE_NUMBER_ID"),
    ADMIN_LIVE: P.getProperty("ADMIN_LIVE"),   // Nadine (27843131635)
    ADMIN_TEST: P.getProperty("ADMIN_TEST"),   // Test number
    USE_TEST_ADMIN: true,                      // change to false in production
  };
})();

/* ── Webhook Endpoint ───────────────────────────────────────────── */
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    Logger.log(`📩 Incoming WhatsApp message: ${JSON.stringify(data, null, 2)}`);

    const messages = data?.entry?.[0]?.changes?.[0]?.value?.messages || [];
    if (!messages.length) return ContentService.createTextOutput("No message");

    const msg = messages[0];
    const from = msg.from; // E.164 number e.g., "27735534607"
    const text = (msg.text?.body || "").trim().toUpperCase();

    if (text === "RESCHEDULE") {
      handleRescheduleRequest(from);
    }

    return ContentService.createTextOutput("OK");
  } catch (err) {
    Logger.log(`❌ doPost error: ${err}`);
    return ContentService.createTextOutput("Error");
  }
}

/* ── Core Logic ─────────────────────────────────────────────────── */
function handleRescheduleRequest(clientNumber) {
  const sheetId = PropertiesService.getScriptProperties().getProperty("CLIENT_SHEET_ID");
  const ss = SpreadsheetApp.openById(sheetId);
  const sh = ss.getSheetByName("PilatesHQ Clients");
  const rows = sh.getDataRange().getValues();

  // Try match the client by number
  const client = rows.find(r => String(r[1] || "").replace(/\D/g, "") === String(clientNumber));
  const clientName = client ? client[0] : "Unknown Client";

  // Send WhatsApp alert to admin
  const admin = CONFIG_REPLY.USE_TEST_ADMIN ? CONFIG_REPLY.ADMIN_TEST : CONFIG_REPLY.ADMIN_LIVE;
  const alertText = `🔄 Reschedule Request\n${clientName} asked to reschedule their session.\nNumber: ${clientNumber}`;
  sendTextToAdmin(admin, alertText);

  Logger.log(`📢 Reschedule alert sent for ${clientName} (${clientNumber})`);
}

/* ── WhatsApp Sender ────────────────────────────────────────────── */
function sendTextToAdmin(toE164, message) {
  const url = `https://graph.facebook.com/v19.0/${CONFIG_REPLY.PHONE_NUMBER_ID}/messages`;
  const payload = {
    messaging_product: "whatsapp",
    to: toE164,
    type: "text",
    text: { body: message },
  };
  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    headers: { Authorization: `Bearer ${CONFIG_REPLY.TOKEN}` },
  };
  try {
    UrlFetchApp.fetch(url, options);
    Logger.log(`✅ Alert sent to admin ${toE164}`);
  } catch (e) {
    Logger.log(`❌ Failed to send admin alert: ${e}`);
  }
}
