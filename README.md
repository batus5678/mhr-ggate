# mhr-ggate

> 🇮🇷 [نسخه فارسی](README.fa.md)

> **Purpose:** open source research tool for studying encrypted transport protocols and censorship circumvention techniques. intended for personal, educational, and research use only. use in accordance with the laws of your country.

routes traffic through domain fronting → GAS → your VPS → xray. gaming and UDP supported.

```
your device
  └─► Google CDN IP (DPI sees: www.google.com ✔)
        └─► script.google.com (hidden inside TLS)
              └─► GAS relay
                    └─► your VPS
                          └─► xray (VMess + SplitHTTP)
                                └─► internet / game servers
```

> **why script.google.com being blocked doesn't matter:**
> the client never directly connects to script.google.com.
> it connects to a Google CDN IP with SNI `www.google.com` — which IS accessible.
> the real `Host: script.google.com` header lives inside the encrypted TLS tunnel, invisible to DPI.
> this is domain fronting.

---

## what runs where

| component | runs on | file |
|---|---|---|
| domain fronting proxy | **your device** | `client/proxy.py` |
| GAS relay | **Google's servers** (free) | `gas/Code.gs` |
| relay bridge | **your VPS** | `server/server.py` |
| xray tunnel | **your VPS** | `server/xray_server.json` |

---

## requirements

| where | what |
|---|---|
| your device | Python 3.10+ |
| your VPS | Python 3.10+, xray-core, nginx |
| Google | a Google account (free) |
| client app | v2rayN / NekoBox / Hiddify (optional, for vmess:// link) |

---

## setup

### step 1 — VPS: install xray

ssh into your VPS and run:

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

generate a UUID — save it, you'll need it in every config:

```bash
xray uuid
# example output: 550e8400-e29b-41d4-a716-446655440000
```

---

### step 2 — VPS: configure and run xray

edit `server/xray_server.json` — paste your UUID:

```json
"id": "550e8400-e29b-41d4-a716-446655440000"
```

copy the file to your VPS and run xray:

```bash
xray run -config /path/to/server/xray_server.json
```

xray will listen on `127.0.0.1:10000` — **localhost only, not exposed to the internet**.

to verify xray is running:
```bash
curl http://127.0.0.1:10000/mhr
# should return something (even an error), not "connection refused"
```

---

### step 3 — VPS: run the relay server

```bash
pip install fastapi uvicorn httpx --break-system-packages

export MHR_SECRET="pick_any_secret_key_here"
export XRAY_PORT=10000
export XRAY_PATH=/mhr

python3 server/server.py
# starts on 0.0.0.0:8080
```

test it locally on the VPS:
```bash
curl http://localhost:8080/health
# should return: {"status":"ok","xray":"127.0.0.1:10000/mhr"}
```

if you get 502 it means xray isn't running. go back to step 2.

---

### step 4 — VPS: put server behind nginx + TLS

install nginx and certbot, then create `/etc/nginx/sites-available/mhr-ggate`:

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
    }
}
```

```bash
ln -s /etc/nginx/sites-available/mhr-ggate /etc/nginx/sites-enabled/
certbot --nginx -d yourdomain.com
nginx -t && systemctl reload nginx
```

no domain? a self-signed cert + raw IP works too:
```bash
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes
```
then update nginx to use `cert.pem` and `key.pem`.

---

### step 5 — Google: deploy the GAS relay

1. go to [script.google.com](https://script.google.com) → **New project**
2. delete all default code, paste the contents of `gas/Code.gs`
3. edit the top two lines:
```js
var VPS_URL = "https://yourdomain.com";    // your VPS URL from step 4
var SECRET  = "pick_any_secret_key_here";  // same key as step 3
```
4. click **Deploy → New deployment**
   - type: **Web app**
   - execute as: **Me**
   - who has access: **Anyone**
5. click **Deploy**, copy the deployment URL:
```
https://script.google.com/macros/s/AKfycb.../exec
```

---

### step 6 — your device: set up config

```bash
cp config.example.json config.json
```

edit `config.json`:
```json
{
  "google_ip":    "216.239.38.120",
  "front_domain": "www.google.com",
  "script_id":    "AKfycb...",
  "auth_key":     "pick_any_secret_key_here",
  "listen_host":  "127.0.0.1",
  "socks5_port":  1080,
  "log_level":    "INFO"
}
```

- `google_ip` — a Google CDN IP. default works. you can also use the whitelisted Akamai IPs.
- `front_domain` — what DPI sees as SNI. leave as `www.google.com`.
- `script_id` — the long ID from your GAS deployment URL (the part between `/s/` and `/exec`)
- `auth_key` — same secret key from steps 3 and 5

---

### step 7 — your device: run the proxy

```bash
cd client
python3 proxy.py -c ../config.json
```

you should see:
```
  mhr-ggate | Domain Fronting Proxy
  Fronting IP   : 216.239.38.120
  SNI (DPI sees): www.google.com
  Real host     : script.google.com (inside TLS)
  SOCKS5        : 127.0.0.1:1080
```

set your browser or system proxy to **SOCKS5 `127.0.0.1:1080`**.

---

### optional — generate vmess:// config for v2rayN / Hiddify

```bash
python3 v2ray/generate_config.py \
  --gas-url "https://script.google.com/macros/s/AKfycb.../exec" \
  --uuid    "550e8400-e29b-41d4-a716-446655440000"
```

outputs a `vmess://` link — paste it into v2rayN, NekoBox, or Hiddify.

---

## gaming

set your game launcher to SOCKS5 `127.0.0.1:1080`.

on Windows use [Proxifier](https://www.proxifier.com/) to route any game automatically.

UDP works because xray's xudp mux wraps UDP inside the VMess tunnel.

---

## troubleshooting

**getting 404 on server:**
- check xray is running: `curl http://127.0.0.1:10000/mhr`
- check `XRAY_PATH` env var matches the path in `xray_server.json` (both should be `/mhr`)
- check the health endpoint: `curl http://localhost:8080/health`

**getting 403 on server:**
- `auth_key` in `config.json` doesn't match `MHR_SECRET` on VPS and `SECRET` in `Code.gs`
- all three must be the same value

**getting 502 on server:**
- xray is not running — go back to step 2

**can't connect at all from Iran:**
- make sure you're running `client/proxy.py` — this handles the domain fronting
- do NOT connect to the VPS directly; the client must go through domain fronting first

**myenv / virtualenv:**
- perfectly fine to run `server.py` inside a virtualenv
- just make sure the env vars are set before running

---

## files

```
mhr-ggate/
├── client/
│   ├── fronting.py          # domain fronting brain (TLS SNI swap)
│   └── proxy.py             # local SOCKS5 proxy — run this on your device
├── gas/
│   └── Code.gs              # paste into Google Apps Script
├── server/
│   ├── server.py            # relay bridge — run this on your VPS
│   └── xray_server.json     # xray config — run this on your VPS
├── v2ray/
│   └── generate_config.py   # generates vmess:// link
├── config.example.json      # copy to config.json and fill in values
└── README.md
```

---

## notes

- GAS free tier: ~20k URL fetches/day. enough for personal use. need more? deploy a second GAS from another Google account.
- SplitHTTP has no WebSocket upgrade handshake — harder to fingerprint.
- your VPS IP is never directly dialed by anyone — only GAS calls it. firewall all ports except 443.

---

## credits

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — original GAS → CF Workers + domain fronting idea
- [masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — original relay concept
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — the actual tunnel

---

contributions welcome, PRs open.
