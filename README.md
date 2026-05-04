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
> the real `Host: script.google.com` lives inside the encrypted TLS tunnel, invisible to DPI.
> this is domain fronting.

---

## what runs where

| component | runs on | file |
|---|---|---|
| domain fronting proxy | **your Windows PC** | `client/proxy.py` |
| GAS relay | **Google's servers** (free) | `gas/Code.gs` |
| relay bridge | **your VPS** | `server/server.py` |
| xray tunnel | **your VPS** | `server/xray_server.json` |

---

## requirements

| where | what |
|---|---|
| your Windows PC | Python 3.10+ |
| your VPS | Python 3.10+, xray-core, nginx |
| Google | a Google account (free) |
| client app | v2rayN / NekoBox / Hiddify (optional) |

---

## setup

### step 0 — clone the repo

**on your Windows PC** (in CMD or PowerShell):
```cmd
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

don't have git? download it from [git-scm.com](https://git-scm.com/download/win) and install it first.

**on your VPS** (in SSH):
```bash
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

---

### step 1 — VPS: install xray

ssh into your VPS and run:

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

generate a UUID — save it, you'll need it in every config:

```bash
xray uuid
# example: 550e8400-e29b-41d4-a716-446655440000
```

---

### step 2 — VPS: configure and run xray

open `server/xray_server.json` with nano:
```bash
nano ~/mhr-ggate/server/xray_server.json
```

paste your UUID here:
```json
"id": "550e8400-e29b-41d4-a716-446655440000"
```

save and exit nano: press **Ctrl+X** then **Y** then **Enter**

run xray in the background:
```bash
xray run -config ~/mhr-ggate/server/xray_server.json &
```

verify xray is running:
```bash
curl http://127.0.0.1:10000/mhr
# should return something, not "connection refused"
```

---

### step 3 — VPS: install nginx

```bash
apt update
apt install nginx certbot python3-certbot-nginx -y
```

create the nginx config:
```bash
nano /etc/nginx/sites-available/mhr-ggate
```

paste this — replace `yourdomain.com` with your actual domain:
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass       http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

save and exit (Ctrl+X → Y → Enter), then enable it:
```bash
ln -s /etc/nginx/sites-available/mhr-ggate /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

get your SSL certificate:
```bash
certbot --nginx -d yourdomain.com
```

> if certbot fails with "unauthorized": your domain DNS is probably behind Cloudflare proxy (orange cloud). go to Cloudflare DNS, click the orange cloud to make it grey (DNS only), wait 2 minutes, then run certbot again. you can turn the orange cloud back on after.

test nginx is working:
```bash
curl https://yourdomain.com/health
# should return: {"status":"ok","xray":"127.0.0.1:10000/mhr"}
```

---

### step 4 — VPS: run the relay server

install dependencies:
```bash
pip install fastapi uvicorn httpx --break-system-packages
```

run it in the background with screen so it survives SSH disconnect:
```bash
apt install screen -y
screen -S mhr

export MHR_SECRET="pick_any_secret_key"
python3 ~/mhr-ggate/server/server.py &

# detach from screen: press Ctrl+A then D
```

test:
```bash
curl http://localhost:8080/health
# {"status":"ok","xray":"127.0.0.1:10000/mhr"}
```

---

### step 5 — Google: deploy the GAS relay

1. go to [script.google.com](https://script.google.com) → click **New project**
2. delete ALL the default code in the editor
3. open `gas/Code.gs` from the repo, copy everything, paste it in
4. edit only these two lines at the very top:
```js
var VPS_URL = "https://yourdomain.com";   // your VPS domain from step 3
var SECRET  = "pick_any_secret_key";      // same key from step 4
```
5. click **Deploy** (top right) → **New deployment**
6. click the gear ⚙ icon next to "type" → select **Web app**
7. set:
   - Execute as: **Me**
   - Who has access: **Anyone**
8. click **Deploy** → **Authorize access** → pick your Google account → **Allow**
9. copy the URL — looks like:
```
https://script.google.com/macros/s/AKfycb.../exec
```
the `script_id` is the long part between `/s/` and `/exec`

---

### step 6 — Windows PC: set up config

go to your `mhr-ggate` folder, find `config.example.json`:
- right click it → Copy → Paste → rename the copy to `config.json`
- right click `config.json` → Open with → Notepad

fill in your values:
```json
{
  "google_ip":    "216.239.38.120",
  "front_domain": "www.google.com",
  "script_id":    "AKfycb...",
  "auth_key":     "pick_any_secret_key",
  "listen_host":  "127.0.0.1",
  "socks5_port":  1080,
  "log_level":    "INFO"
}
```

- `google_ip` — leave as default. or use one of the whitelisted Akamai IPs.
- `front_domain` — leave as `www.google.com`
- `script_id` — the long ID from your GAS URL (between `/s/` and `/exec`)
- `auth_key` — same secret key from steps 4 and 5

save the file.

---

### step 7 — Windows PC: run the proxy

open CMD in the mhr-ggate folder:
- hold **Shift** + right click inside the `mhr-ggate` folder → "Open PowerShell window here"

or open CMD manually:
```cmd
cd C:\Users\YourName\mhr-ggate\client
python proxy.py -c ../config.json
```

leave this CMD window open the whole time you want to use the proxy. closing it disconnects you.

you should see:
```
  mhr-ggate | Domain Fronting Proxy
  Fronting IP   : 216.239.38.120
  SNI (DPI sees): www.google.com
  Real host     : script.google.com (inside TLS)
  SOCKS5        : 127.0.0.1:1080
```

---

### step 8 — set your proxy

**browser (Firefox):**
Settings → search "proxy" → Manual proxy → SOCKS5 → Host: `127.0.0.1` Port: `1080`

**browser (Chrome):**
install [FoxyProxy](https://chrome.google.com/webstore/detail/foxyproxy/gcknhkkoolaabfmlnjonogaaifnjlfnp) → add proxy → SOCKS5 → `127.0.0.1:1080`

**system wide (Windows):**
Settings → Network & Internet → Proxy → Manual proxy setup → turn on → Address: `127.0.0.1` Port: `1080`

**gaming (Windows):**
download [Proxifier](https://www.proxifier.com/) → Profile → Proxy Servers → Add → `127.0.0.1` port `1080` SOCKS5 → then route your game through it

---

## gaming

UDP works because xray's xudp mux wraps UDP inside the VMess tunnel. use Proxifier on Windows to route any game automatically without the game needing built-in proxy support.

---

## troubleshooting

**404 on server:**
- check xray is running: `curl http://127.0.0.1:10000/mhr`
- check health: `curl http://localhost:8080/health`
- make sure `XRAY_PATH=/mhr` matches path in `xray_server.json`

**403 on server:**
- `auth_key` in `config.json`, `MHR_SECRET` on VPS, and `SECRET` in `Code.gs` must all be the exact same value

**502 on server:**
- xray crashed — run it again: `xray run -config ~/mhr-ggate/server/xray_server.json &`

**certbot unauthorized error:**
- turn off Cloudflare proxy (orange cloud → grey) in your DNS settings, wait 2 min, try again

**can't connect from Iran:**
- make sure `client/proxy.py` is running on your PC — this is what handles domain fronting
- do NOT connect to the VPS directly

**proxy.py crashes on Windows:**
- make sure Python is installed: `python --version`
- install if missing: [python.org/downloads](https://python.org/downloads) — check "Add to PATH" during install

**everything was working then stopped after SSH disconnect:**
- use screen on VPS so processes survive disconnect:
```bash
screen -r mhr   # reconnect to your screen session
```

---

## files

```
mhr-ggate/
├── client/
│   ├── fronting.py          # domain fronting brain (TLS SNI swap)
│   ├── proxy.py             # local SOCKS5 proxy — run on your Windows PC
│   └── certs.py
├── gas/
│   └── Code.gs              # paste into Google Apps Script
├── server/
│   ├── server.py            # relay bridge — run on VPS
│   └── xray_server.json     # xray config — run on VPS
├── v2ray/
│   └── generate_config.py   # generates vmess:// link for v2rayN/Hiddify
├── config.example.json      # copy to config.json and fill in values
└── README.md
```

---

## notes

- GAS free tier: ~20k URL fetches/day. enough for personal use. need more? deploy a second GAS from another Google account.
- SplitHTTP has no WebSocket upgrade handshake — harder to fingerprint.
- your VPS IP is never directly dialed — only GAS calls it. firewall everything except port 443.

---

## credits

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — original GAS + domain fronting idea
- [masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — original relay concept
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — the actual tunnel

---

contributions welcome, PRs open.
