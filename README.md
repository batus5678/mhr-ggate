# mhr-ggate

> 🇮🇷 [نسخه فارسی](README.fa.md)

> **Purpose:** open-source research tool for studying encrypted transport protocols and censorship circumvention techniques.  
> Intended for personal, educational, and research use only. Use in accordance with the laws of your country.

Routes traffic through **domain fronting → Google Apps Script → your VPS → xray**, bypassing DPI inspection at the SNI level.  
Gaming and UDP are both supported via xray's xudp mux.

```
your device
  └─► Google CDN IP  (DPI sees: www.google.com ✔)
        └─► script.google.com  (hidden inside TLS — invisible to DPI)
              └─► GAS relay
                    └─► your VPS  (server.py)
                          └─► xray  (VMess + xhttp, packet-up)
                                └─► internet / game servers
```

> **Why does this work even when script.google.com is blocked?**  
> The client never dials script.google.com directly.  
> It connects to a Google CDN IP with SNI `www.google.com` — which is accessible.  
> The `Host: script.google.com` header lives inside the encrypted TLS tunnel,  
> invisible to Deep Packet Inspection (DPI).  This technique is called **domain fronting**.

---

## v2 — What changed (bug fixes)

| Issue | Root cause | Fix |
|---|---|---|
| GAS couldn't relay VMess binary | `e.postData.contents` treated bytes as UTF-8 string | Client now base64-encodes before sending; GAS passes the ASCII string through untouched |
| Double base64 encoding | Original `Code.gs` called `Utilities.base64Encode()` on a response already encoded by `server.py` | Removed second encoding — GAS now returns `resp.getContentText()` directly |
| GAS 6-minute execution cap | SplitHTTP download leg is a long-lived stream | Switched to `xhttp` with `mode: "packet-up"` — every request is short and self-contained |
| Timing attack on secret check | Plain string `!=` comparison leaks timing information | Replaced with `hmac.compare_digest()` |
| `server.py` Python SyntaxError | Broken indentation in original file | Full rewrite with correct formatting |
| No error handling | Bad payloads / xray downtime caused unhandled exceptions | Graceful 400 / 502 / 504 responses with structured logging |
| Binary corruption on relay path | Local xray's xhttp outbound sent raw bytes to GAS | New `client_relay.py` intercepts xray's HTTP requests and base64-wraps the body |

---

## Architecture — what runs where

| Component | Where | File |
|---|---|---|
| **Client Relay** *(new)* | Your device | `client/client_relay.py` |
| Domain fronting core | Your device | `client/fronting.py` |
| MITM proxy *(browser)* | Your device | `client/proxy.py` |
| GAS relay | Google's servers (free) | `gas/Code.gs` |
| Relay bridge | Your VPS | `server/server.py` |
| xray tunnel | Your VPS | `server/xray_server.json` |

---

## Requirements

| Where | What |
|---|---|
| Your device | Python 3.10+, xray-core *(optional, for games)* |
| Your VPS | Python 3.10+, xray-core, nginx |
| Google | A Google account (free) |

---

## Setup

### Step 1 — VPS: install xray-core

SSH into your VPS and run the official installer:

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

Generate a UUID and save it — you will need it in every config file:

```bash
xray uuid
# example: 550e8400-e29b-41d4-a716-446655440000
```

---

### Step 2 — VPS: configure xray

Edit `server/xray_server.json` and paste your UUID:

```json
"id": "550e8400-e29b-41d4-a716-446655440000"
```

Copy the file to your VPS and run xray:

```bash
xray run -config /path/to/server/xray_server.json
```

xray listens on `127.0.0.1:10000` — **localhost only, never exposed to the internet**.

Verify xray is running:

```bash
curl http://127.0.0.1:10000/mhr
# should return something (even an error), not "connection refused"
```

---

### Step 3 — VPS: run the relay server

```bash
pip install fastapi uvicorn httpx --break-system-packages

export MHR_SECRET="pick_any_secret_key_here"
export XRAY_PORT=10000
export XRAY_PATH=/mhr

python3 server/server.py
# starts on 0.0.0.0:8080
```

Test it locally:

```bash
curl http://localhost:8080/health
# {"status":"ok","xray":"127.0.0.1:10000/mhr","uptime_s":5}
```

If you get 502, xray is not running — go back to step 2.

---

### Step 4 — VPS: nginx + TLS

Install nginx and certbot, then create `/etc/nginx/sites-available/mhr-ggate`:

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/mhr-ggate /etc/nginx/sites-enabled/
certbot --nginx -d yourdomain.com
nginx -t && systemctl reload nginx
```

No domain? A self-signed cert and raw IP also work:

```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes
```

---

### Step 5 — Google: deploy GAS relay

1. Go to [script.google.com](https://script.google.com) → **New project**
2. Delete all default code and paste the contents of `gas/Code.gs`
3. Edit the top two lines:

```js
var VPS_URL = "https://yourdomain.com";      // your VPS from step 4
var SECRET  = "pick_any_secret_key_here";    // same as MHR_SECRET in step 3
```

4. Click **Deploy → New deployment**
   - Type: **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**

5. Click **Deploy** and copy the deployment URL:

```
https://script.google.com/macros/s/AKfycb.../exec
```

The script ID is the long string between `/s/` and `/exec`.

---

### Step 6 — Device: set up config.json

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "google_ip":    "216.239.38.120",
  "front_domain": "www.google.com",
  "script_id":    "AKfycb...",
  "auth_key":     "pick_any_secret_key_here",
  "listen_host":  "127.0.0.1",
  "socks5_port":  1080,
  "listen_port":  8085,
  "relay_port":   10002,
  "log_level":    "INFO"
}
```

Field reference:

- `google_ip` — a Google CDN IP. The default works for most regions. You can also use whitelisted Akamai IPs.
- `front_domain` — what Iran's DPI sees as the TLS SNI. Leave as `www.google.com`.
- `script_id` — from your GAS deployment URL (the part between `/s/` and `/exec`).
- `auth_key` — the same secret from steps 3 and 5.
- `relay_port` — port that `client_relay.py` listens on. Local xray connects here.

---

### Step 7 — Device: start services

#### Option A — Windows (recommended): GUI launcher

Double-click `start.bat` — it installs dependencies, validates config, and opens the GUI.  
From the GUI you can start/stop each service and watch live logs.

Or run directly:

```cmd
python launcher.py
```

#### Option B — Command line (any OS)

Open three terminal windows:

**Terminal 1 — Client relay** (required for xray path):

```bash
cd client
python3 client_relay.py -c ../config.json
```

**Terminal 2 — Local xray** (for SOCKS5 / games):

Edit `client/xray_client.json`, paste your UUID, then:

```bash
xray run -config client/xray_client.json
```

Set your browser or system proxy to **SOCKS5 `127.0.0.1:1080`**.

**Terminal 3 — MITM proxy** (browser only, alternative to xray):

```bash
cd client
python3 proxy.py -c ../config.json
```

Set browser proxy to **HTTP `127.0.0.1:8085`**.  
On first run, the CA cert is generated and installed automatically (Windows/macOS).  
Firefox users need to import `client/ca/ca.crt` manually in browser settings.

---

### Optional — generate vmess:// link for v2rayN / Hiddify / NekoBox

```bash
python3 v2ray/generate_config.py \
  --gas-url "https://script.google.com/macros/s/AKfycb.../exec" \
  --uuid    "550e8400-e29b-41d4-a716-446655440000"
```

Outputs a `vmess://` link. Paste it into v2rayN, NekoBox, or Hiddify.

---

## One-command VPS install

```bash
export MHR_SECRET="your_secret"
export MHR_DOMAIN="yourdomain.com"   # optional, enables TLS
bash install.sh
```

The script installs xray, Python deps, creates systemd units for both services,  
configures nginx, and runs certbot — everything in one pass.

---

## Docker (VPS)

```bash
export MHR_SECRET="your_secret"
docker compose up -d
```

---

## Gaming

Set your game launcher's proxy to **SOCKS5 `127.0.0.1:1080`**.  
On Windows, use [Proxifier](https://www.proxifier.com/) to route any game automatically without per-game settings.  
UDP works because xray's xudp mux wraps UDP inside the VMess tunnel.

---

## Troubleshooting

**404 from server:**  
Check xray is running: `curl http://127.0.0.1:10000/mhr`  
Check `XRAY_PATH` env var matches `xhttpSettings.path` in `xray_server.json` (both should be `/mhr`).

**403 from server:**  
`auth_key` in `config.json`, `MHR_SECRET` on VPS, and `SECRET` in `Code.gs` must all be identical.

**502 from server:**  
xray is not running on the VPS — go back to step 2.

**GAS_ERR in client logs:**  
GAS couldn't reach your VPS. Verify the VPS is reachable on port 443 and `VPS_URL` in `Code.gs` is correct.

**Binary / garbage response from relay:**  
Ensure you are using the **v2** `Code.gs` — the original had a double-encoding bug that corrupted binary payloads.

**Cannot connect at all from Iran:**  
Run `client_relay.py` and confirm local xray is pointed at `127.0.0.1:10002`.  
Do not connect to the VPS directly — all traffic must flow through GAS via domain fronting.

**MITM proxy — browser shows SSL error:**  
The CA cert hasn't been trusted yet. On Windows, re-run `proxy.py` once as Administrator, or manually import `client/ca/ca.crt` into your OS trust store.

---

## File map

```
mhr-ggate/
├── client/
│   ├── client_relay.py      ← NEW: base64 relay between local xray and GAS
│   ├── xray_client.json     ← NEW: local xray config (SOCKS5 inbound, xhttp out)
│   ├── fronting.py          domain fronting core — TLS SNI swap
│   ├── proxy.py             MITM HTTP/HTTPS proxy (browser use)
│   └── certs.py             auto CA + per-domain cert generator
├── gas/
│   └── Code.gs              paste into Google Apps Script
├── server/
│   ├── server.py            VPS relay bridge
│   └── xray_server.json     VPS xray config (xhttp inbound, packet-up)
├── v2ray/
│   └── generate_config.py   generates vmess:// link
├── config.example.json      copy to config.json and fill in your values
├── launcher.py              ← NEW: Windows GUI launcher
├── start.bat                ← NEW: Windows one-click start
├── install.sh               ← NEW: VPS one-command installer
├── docker-compose.yml       ← NEW: Docker VPS deployment
└── README.md
```

---

## Notes

GAS free tier allows roughly 20,000 URL fetches per day — sufficient for personal use.  
Need more? Deploy a second GAS from a different Google account.

Using `xhttp` with `mode: "packet-up"` means every request is short and self-contained,  
well within GAS's 6-minute execution limit.

Your VPS IP is never dialled directly by any client — only GAS connects to it.  
Firewall all ports except 443; this prevents passive enumeration of your VPS.

---

## Credits

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — original GAS + domain fronting concept
- [masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — original relay concept
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — the tunnel engine

---

Contributions welcome — PRs open.
