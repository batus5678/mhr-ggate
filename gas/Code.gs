/**
 * mhr-gvps | Google Apps Script Relay
 * Routes traffic through script.google.com → your VPS
 * Deploy as: Web App → Anyone → Execute as Me
 */

// ─── CONFIG ───────────────────────────────────────────────
var VPS_URL = "https://YOUR_VPS_IP_OR_DOMAIN";  // e.g. https://1.2.3.4 or https://yourdomain.com
var SECRET  = "CHANGE_THIS_SECRET_KEY";          // must match server
// ──────────────────────────────────────────────────────────

function doPost(e) {
  try {
    var body    = e.postData.contents;
    var headers = {};

    // Forward relevant headers from client
    var incoming = e.parameter;
    if (e.postData.type) headers["Content-Type"] = e.postData.type;
    headers["X-MHR-Secret"] = SECRET;
    headers["X-MHR-Path"]   = incoming["path"] || "/";

    var path    = incoming["path"] || "/";
    var target  = VPS_URL + path;

    var options = {
      method      : "post",
      contentType : e.postData.type || "application/octet-stream",
      payload     : body,
      headers     : headers,
      muteHttpExceptions: true,
      followRedirects   : true,
    };

    var response = UrlFetchApp.fetch(target, options);
    var code     = response.getResponseCode();
    var respBody = response.getContent(); // byte[]

    return ContentService
      .createTextOutput(Utilities.base64Encode(respBody))
      .setMimeType(ContentService.MimeType.TEXT);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  // Health check + SplitHTTP GET leg
  var incoming = e.parameter;
  var path     = incoming["path"] || "/";
  var headers  = {};
  headers["X-MHR-Secret"] = SECRET;
  headers["X-MHR-Path"]   = path;

  var target = VPS_URL + path;
  var options = {
    method : "get",
    headers: headers,
    muteHttpExceptions: true,
  };

  try {
    var response = UrlFetchApp.fetch(target, options);
    var respBody = response.getContent();
    return ContentService
      .createTextOutput(Utilities.base64Encode(respBody))
      .setMimeType(ContentService.MimeType.TEXT);
  } catch (err) {
    return ContentService
      .createTextOutput("ok")
      .setMimeType(ContentService.MimeType.TEXT);
  }
}
