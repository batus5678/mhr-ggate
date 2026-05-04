# mhr-ggate

> 🇬🇧 [English README](README.md)

> **هدف:** ابزار متن‌باز برای مطالعه پروتکل‌های رمزگذاری و دور زدن سانسور. فقط برای استفاده شخصی، آموزشی و پژوهشی.

ترافیک رو از طریق دامین فرانتینگ → GAS → VPS خودت → xray هدایت می‌کنه. بازی آنلاین و UDP هم کار می‌کنه.

```
دستگاه شما
  └─► Google CDN IP (فیلترینگ می‌بینه: www.google.com ✔)
        └─► script.google.com (داخل TLS مخفیه)
              └─► GAS relay
                    └─► VPS شما
                          └─► xray (VMess + SplitHTTP)
                                └─► اینترنت / سرور بازی
```

> **چرا بلاک بودن script.google.com مهم نیست:**
> کلاینت هیچ‌وقت مستقیم به script.google.com وصل نمی‌شه.
> به یه IP از CDN گوگل وصل می‌شه با SNI برابر `www.google.com` — که باز هست.
> هدر `Host: script.google.com` داخل تونل TLS رمزگذاری شده‌ست و فیلترینگ نمی‌تونه ببینتش.
> این یعنی دامین فرانتینگ.

---

## چی کجا اجرا می‌شه

| قسمت | کجا اجرا می‌شه | فایل |
|---|---|---|
| پروکسی دامین فرانتینگ | **دستگاه شما** | `client/proxy.py` |
| رله GAS | **سرورهای گوگل** (رایگان) | `gas/Code.gs` |
| برید رله | **VPS شما** | `server/server.py` |
| تونل xray | **VPS شما** | `server/xray_server.json` |

---

## نیازمندی‌ها

| کجا | چی |
|---|---|
| دستگاه شما | Python 3.10+ |
| VPS | Python 3.10+، xray-core، nginx |
| گوگل | یه حساب گوگل (رایگان) |
| اپ کلاینت | v2rayN / NekoBox / Hiddify (اختیاری) |

---

## راه‌اندازی

### مرحله ۱ — VPS: نصب xray

وارد VPS بشو و اجرا کن:

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

یه UUID بساز — نگهش دار، توی همه کانفیگ‌ها لازمته:

```bash
xray uuid
# مثال: 550e8400-e29b-41d4-a716-446655440000
```

---

### مرحله ۲ — VPS: کانفیگ و اجرای xray

فایل `server/xray_server.json` رو ویرایش کن، UUID رو پیست کن:

```json
"id": "550e8400-e29b-41d4-a716-446655440000"
```

فایل رو روی VPS کپی کن و xray رو اجرا کن:

```bash
xray run -config /path/to/server/xray_server.json
```

xray روی `127.0.0.1:10000` گوش می‌ده — **فقط localhost، به اینترنت expose نشده**.

برای تست اینکه xray در حال اجراست:
```bash
curl http://127.0.0.1:10000/mhr
# باید یه چیزی برگردونه (حتی error)، نه "connection refused"
```

---

### مرحله ۳ — VPS: اجرای relay server

```bash
pip install fastapi uvicorn httpx --break-system-packages

export MHR_SECRET="یه_کلید_سری_دلخواه"
export XRAY_PORT=10000
export XRAY_PATH=/mhr

python3 server/server.py
# روی 0.0.0.0:8080 شروع می‌کنه
```

تست لوکال روی VPS:
```bash
curl http://localhost:8080/health
# باید برگردونه: {"status":"ok","xray":"127.0.0.1:10000/mhr"}
```

اگه 502 گرفتی یعنی xray در حال اجرا نیست. برگرد مرحله ۲.

---

### مرحله ۴ — VPS: قرار دادن server پشت nginx + TLS

nginx و certbot رو نصب کن، سپس فایل `/etc/nginx/sites-available/mhr-ggate` رو بساز:

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

دامنه نداری؟ سرتیفیکت self-signed با IP مستقیم هم کار می‌کنه.

---

### مرحله ۵ — گوگل: دیپلوی GAS relay

۱. برو به [script.google.com](https://script.google.com) ← **New project**
۲. همه کد پیش‌فرض رو پاک کن، محتوای `gas/Code.gs` رو پیست کن
۳. دو خط اول رو ویرایش کن:
```js
var VPS_URL = "https://yourdomain.com";    // آدرس VPS از مرحله ۴
var SECRET  = "یه_کلید_سری_دلخواه";       // همون کلید مرحله ۳
```
۴. روی **Deploy ← New deployment** کلیک کن
   - type: **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**
۵. Deploy کن، لینک deployment رو کپی کن:
```
https://script.google.com/macros/s/AKfycb.../exec
```

---

### مرحله ۶ — دستگاه شما: تنظیم config

```bash
cp config.example.json config.json
```

فایل `config.json` رو ویرایش کن:
```json
{
  "google_ip":    "216.239.38.120",
  "front_domain": "www.google.com",
  "script_id":    "AKfycb...",
  "auth_key":     "یه_کلید_سری_دلخواه",
  "listen_host":  "127.0.0.1",
  "socks5_port":  1080,
  "log_level":    "INFO"
}
```

- `google_ip` — IP از CDN گوگل. مقدار پیش‌فرض کار می‌کنه. می‌تونی از IPهای وایت‌لیست Akamai هم استفاده کنی.
- `front_domain` — چیزی که فیلترینگ به عنوان SNI می‌بینه. همون `www.google.com` بذار.
- `script_id` — ID طولانی از URL deployment GAS (قسمت بین `/s/` و `/exec`)
- `auth_key` — همون کلید سری از مراحل ۳ و ۵

---

### مرحله ۷ — دستگاه شما: اجرای پروکسی

```bash
cd client
python3 proxy.py -c ../config.json
```

باید ببینی:
```
  mhr-ggate | Domain Fronting Proxy
  Fronting IP   : 216.239.38.120
  SNI (DPI sees): www.google.com
  Real host     : script.google.com (inside TLS)
  SOCKS5        : 127.0.0.1:1080
```

پروکسی سیستم یا مرورگرت رو روی **SOCKS5 `127.0.0.1:1080`** تنظیم کن.

---

### اختیاری — ساخت لینک vmess:// برای v2rayN / Hiddify

```bash
python3 v2ray/generate_config.py \
  --gas-url "https://script.google.com/macros/s/AKfycb.../exec" \
  --uuid    "550e8400-e29b-41d4-a716-446655440000"
```

یه لینک `vmess://` می‌سازه که مستقیم توی v2rayN، NekoBox یا Hiddify پیستش کنی.

---

## بازی آنلاین

لانچر بازیت رو روی SOCKS5 `127.0.0.1:1080` تنظیم کن.

روی ویندوز از [Proxifier](https://www.proxifier.com/) استفاده کن تا هر بازی رو بدون تنظیمات داخلی روت کنه.

UDP کار می‌کنه چون xudp mux توی xray، داده‌های UDP رو داخل تونل VMess رپ می‌کنه.

---

## عیب‌یابی

**خطای 404 روی سرور:**
- چک کن xray در حال اجراست: `curl http://127.0.0.1:10000/mhr`
- چک کن `XRAY_PATH` با path توی `xray_server.json` یکی باشه (هر دو `/mhr`)
- health endpoint: `curl http://localhost:8080/health`

**خطای 403 روی سرور:**
- `auth_key` در `config.json` با `MHR_SECRET` روی VPS و `SECRET` در `Code.gs` یکی نیست
- هر سه باید یه مقدار باشن

**خطای 502 روی سرور:**
- xray در حال اجرا نیست — برگرد مرحله ۲

**اصلاً از ایران وصل نمی‌شه:**
- مطمئن شو `client/proxy.py` رو اجرا کردی — این قسمت دامین فرانتینگ رو انجام می‌ده
- مستقیم به VPS وصل نشو، کلاینت باید از دامین فرانتینگ رد بشه

**myenv / virtualenv:**
- کاملاً اوکیه که `server.py` رو داخل virtualenv اجرا کنی
- فقط مطمئن شو env var ها قبل از اجرا set شدن

---

## فایل‌ها

```
mhr-ggate/
├── client/
│   ├── fronting.py          # مغز دامین فرانتینگ (SNI swap)
│   └── proxy.py             # پروکسی SOCKS5 لوکال — روی دستگاه خودت اجرا کن
├── gas/
│   └── Code.gs              # پیست کن توی Google Apps Script
├── server/
│   ├── server.py            # relay bridge — روی VPS اجرا کن
│   └── xray_server.json     # کانفیگ xray — روی VPS اجرا کن
├── v2ray/
│   └── generate_config.py   # لینک vmess:// می‌سازه
├── config.example.json      # کپی کن به config.json و پر کن
└── README.md
```

---

## نکات

- پلن رایگان GAS: ~۲۰ هزار URL fetch در روز. برای استفاده شخصی کافیه. بیشتر لازم داری؟ از یه حساب گوگل دیگه یه GAS دیگه deploy کن.
- SplitHTTP نیاز به WebSocket upgrade handshake نداره — سخت‌تر fingerprint می‌شه.
- IP سرور هیچ‌وقت مستقیم دیال نمی‌شه — فقط GAS بهش وصل می‌شه. همه پورت‌ها رو فایروال کن جز ۴۴۳.

---

## کردیت‌ها

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — ایده اصلی GAS + دامین فرانتینگ
- [masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — کانسپت اصلی relay
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — تونل اصلی

---

مشارکت خوشحال می‌کنیم، PR باز.
