# mhr-ggate

> 🇮🇷 [نسخه فارسی](README.fa.md)

routes traffic through Google Apps Script → your own VPS instead of Cloudflare Workers. based on [mhr-cfw](https://github.com/denuitt1/mhr-cfw) but with a real xray tunnel underneath so UDP and gaming actually work.

```
you → script.google.com → your VPS → internet
```

GAS runs on Google's domain so it basically never gets blocked. your VPS stays hidden, nobody connects to it directly.

---

## what's different from mhr-cfw

mhr-cfw uses Cloudflare Workers as the backend and just HTTP-proxies raw traffic. that's why games don't work and most apps break — there's no real tunnel.

mhr-ggate puts xray on your VPS with VMess + SplitHTTP transport. GAS forwards to the relay server, relay bridges into xray. full tunnel, UDP included.

| | mhr-cfw | mhr-ggate |
|---|---|---|
| frontend | GAS | GAS |
| backend | Cloudflare Workers | your VPS |
| gaming / UDP | ✖ | ✔ |
| protocol | raw HTTP proxy | VMess + SplitHTTP |
| backend cost | free | ~$3-5/mo VPS |
| you control backend | ✖ | ✔ |

---

## requirements

- a VPS outside Iran (any provider)
- a Google account (free)
- [xray-core](https://github.com/XTLS/Xray-core) on the VPS
- Python 3.10+ on the VPS
- v2rayN / NekoBox / Hiddify on your device

---

## setup

### 1. clone

```bash
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

### 2. install xray on your VPS

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

generate a UUID and save it:

```bash
xray uuid
```

### 3. configure xray server

edit `server/xray_server.json` and paste your UUID:

```json
"id": "YOUR-UUID-HERE"
```

run it:

```bash
xray run -config server/xray_server.json
```

xray listens on `127.0.0.1:10000` — not exposed to the internet.

### 4. run the relay server

```bash
pip install fastapi uvicorn httpx

export MHR_SECRET="pick_a_secret_key"
python3 server/server.py
```

put it behind nginx + TLS on port 443:

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

no domain? a self-signed cert + raw IP works too.

### 5. deploy the GAS relay

1. go to [script.google.com](https://script.google.com) → New Project
2. paste `gas/Code.gs`
3. edit the top of the file:
```js
var VPS_URL = "https://yourdomain.com";
var SECRET  = "pick_a_secret_key";      // same as step 4
```
4. Deploy → New Deployment → Web App
   - Execute as: **Me**
   - Who has access: **Anyone**
5. copy the deployment URL:
```
https://script.google.com/macros/s/XXXXXXXXXX/exec
```

### 6. generate your client config

```bash
python3 v2ray/generate_config.py \
  --gas-url "https://script.google.com/macros/s/XXXXXXXXXX/exec" \
  --uuid    "YOUR-UUID-HERE"
```

outputs `client_config.json` and a `vmess://` link you can paste into any v2ray client.

---

## connecting

```bash
# option A — xray CLI
xray run -config v2ray/client_config.json

# option B — paste the vmess:// link into v2rayN, NekoBox, or Hiddify
```

local proxies after connecting:
- SOCKS5 `127.0.0.1:1080`
- HTTP `127.0.0.1:8118`

---

## gaming

set your game client or launcher to use SOCKS5 `127.0.0.1:1080`.

on Windows you can use [Proxifier](https://www.proxifier.com/) to route any game through it without the game needing built-in proxy support.

UDP works because xray's xudp mux wraps UDP datagrams inside the VMess tunnel.

---

## files

```
mhr-ggate/
├── gas/
│   └── Code.gs              # paste into Google Apps Script
├── server/
│   ├── server.py            # relay server, run on VPS
│   └── xray_server.json     # xray config for VPS
├── v2ray/
│   └── generate_config.py   # generates client config + vmess:// link
└── README.md
```

---

## notes

- GAS free tier gives around 20k URL fetches per day, enough for personal use. if you need more just deploy from a second Google account and split traffic.
- SplitHTTP doesn't need a WebSocket upgrade handshake so it's harder to fingerprint than ws-based configs.
- your VPS IP is never directly dialed by the client — only GAS calls it. keep the relay port firewalled and only expose 443 through nginx.

---

## credits

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — original GAS → CF Workers idea
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — the actual tunnel

---

contributions welcome, PRs open.
