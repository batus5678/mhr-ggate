
var VPS_URL = "https://your-vps-domain.com"; // MUST be your domain with HTTPS
var SECRET  = "YOUR_SECRET_KEY";             // Pick a key

function doPost(e) {
  var target = VPS_URL + (e.parameter.path || "/");
  var options = {
    method: "post",
    payload: e.postData.contents,
    headers: { "X-MHR-Secret": SECRET },
    muteHttpExceptions: true
  };
  var resp = UrlFetchApp.fetch(target, options);
  return ContentService.createTextOutput(Utilities.base64Encode(resp.getContent()));
}

function doGet(e) {
  return ContentService.createTextOutput("Bridge is Active");
}