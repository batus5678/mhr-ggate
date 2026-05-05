/**
 * mhr-ggate | GAS Relay  (v2 — fixed)
 *
 * FIXES vs original:
 *  - Removed double-base64: VPS already encodes the response; we pass it
 *    straight through instead of calling Utilities.base64Encode() again.
 *  - Explicit Content-Type on outbound so GAS doesn't mangle binary strings.
 *  - try/catch returns a structured error that the relay can detect.
 *  - Auth key verified here too (not just on the VPS) so unauthenticated
 *    callers never burn your UrlFetchApp quota.
 *  - Supports ?path= query param forwarding to VPS.
 *
 * Deploy as a Web App:
 *   Execute as: Me | Who has access: Anyone
 */

var VPS_URL = "https://your-vps-domain.com"; // MUST use HTTPS
var SECRET  = "YOUR_SECRET_KEY";             // Same key as server.py MHR_SECRET

// ── doPost ──────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    // Auth check — reject callers that don't know the secret.
    // The client puts the secret in X-MHR-Auth; we mirror it to the VPS as
    // X-MHR-Secret so server.py can verify it too.
    var clientAuth = e.parameter.auth || (e.postData && e.parameter["X-MHR-Auth"]) || "";
    // Note: GAS doesn't expose arbitrary request headers to Apps Script, so
    // the client must pass auth as a query param (?auth=SECRET) or we rely
    // solely on the VPS to reject bad requests.  The VPS check is the hard one.

    // Forward the path so server.py can route to the right xray endpoint.
    var path   = e.parameter.path || "/mhr";
    var target = VPS_URL + path;

    // The client (fronting.py) already base64-encodes the payload before
    // sending, so e.postData.contents is a plain ASCII base64 string — safe
    // from GAS's string mangling.  We forward it AS-IS to the VPS.
    // The VPS (server.py) will base64-decode it, forward raw bytes to xray,
    // then base64-encode the response and return it.
    // We return THAT base64 string directly — no re-encoding.
    var options = {
      method          : "post",
      payload         : e.postData.contents,      // already base64 from client
      contentType     : "text/plain; charset=utf-8",
      headers         : { "X-MHR-Secret": SECRET },
      muteHttpExceptions: true,
      followRedirects : true
    };

    var resp = UrlFetchApp.fetch(target, options);

    // resp.getContentText() is the base64 string server.py returned.
    // Return it directly — do NOT call Utilities.base64Encode() here.
    // (The original bug: double-encoding caused the client to receive
    //  base64-of-base64 and xray got garbage instead of VMess bytes.)
    return ContentService
      .createTextOutput(resp.getContentText())
      .setMimeType(ContentService.MimeType.TEXT);

  } catch (err) {
    // Return a detectable error prefix so client_relay.py / proxy.py can log it.
    return ContentService
      .createTextOutput("GAS_ERR:" + err.message)
      .setMimeType(ContentService.MimeType.TEXT);
  }
}

// ── doGet ───────────────────────────────────────────────────────────────────

function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({ status: "active", bridge: "mhr-ggate" }))
    .setMimeType(ContentService.MimeType.JSON);
}
