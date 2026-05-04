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
> به یه IP از CDN گوگل وصل می‌شه با SNI برابر `www.google.com` که باز هست.
> هدر `Host: script.google.com` داخل تونل TLS رمزگذاری شده‌ست و فیلترینگ نمی‌تونه ببینتش.
> این یعنی دامین فرانتینگ.

---

## چی کجا اجرا می‌شه

| قسمت | کجا اجرا می‌شه | فایل |
|---|---|---|
| پروکسی دامین فرانتینگ | **ویندوز شما** | `client/proxy.py` |
| رله GAS | **سرورهای گوگل** (رایگان) | `gas/Code.gs` |
| برید رله | **VPS شما** | `server/server.py` |
| تونل xray | **VPS شما** | `server/xray_server.json` |

---

## نیازمندی‌ها

| کجا | چی |
|---|---|
| ویندوز شما | Python 3.10+ |
| VPS | Python 3.10+، xray-core، nginx |
| گوگل | یه حساب گوگل (رایگان) |
| اپ کلاینت | v2rayN / NekoBox / Hiddify (اختیاری) |

---

## راه‌اندازی

### مرحله ۰ — کلون کردن ریپو

**روی ویندوز** (در CMD یا PowerShell):
```cmd
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

git نداری؟ از [git-scm.com](https://git-scm.com/download/win) دانلود و نصبش کن.

**روی VPS** (در SSH):
```bash
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

---

### مرحله ۱ — VPS: نصب xray

وارد VPS بشو از طریق SSH و اجرا کن:

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

فایل رو با nano باز کن:
```bash
nano ~/mhr-ggate/server/xray_server.json
```

UUID رو اینجا پیست کن:
```json
"id": "550e8400-e29b-41d4-a716-446655440000"
```

ذخیره و خروج از nano: **Ctrl+X** بعد **Y** بعد **Enter**

xray رو در پس‌زمینه اجرا کن:
```bash
xray run -config ~/mhr-ggate/server/xray_server.json &
```

تست کن xray در حال اجراست:
```bash
curl http://127.0.0.1:10000/mhr
# باید یه چیزی برگردونه، نه "connection refused"
```

---

### مرحله ۳ — VPS: نصب nginx

```bash
apt update
apt install nginx certbot python3-certbot-nginx -y
```

کانفیگ nginx رو بساز:
```bash
nano /etc/nginx/sites-available/mhr-ggate
```

این رو پیست کن — `yourdomain.com` رو با دامنه واقعیت عوض کن:
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

ذخیره کن (Ctrl+X → Y → Enter) بعد فعالش کن:
```bash
ln -s /etc/nginx/sites-available/mhr-ggate /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

سرتیفیکت SSL بگیر:
```bash
certbot --nginx -d yourdomain.com
```

> اگه certbot خطای "unauthorized" داد: احتمالاً دامنه‌ات پشت پروکسی Cloudflare‌ست (ابر نارنجی). برو DNS کلودفلر، روی ابر نارنجی کلیک کن تا خاکستری بشه (DNS only)، ۲ دقیقه صبر کن، دوباره certbot رو اجرا کن. بعد از گرفتن cert می‌تونی ابر نارنجی رو برگردونی.

تست کن nginx کار می‌کنه:
```bash
curl https://yourdomain.com/health
# باید برگردونه: {"status":"ok","xray":"127.0.0.1:10000/mhr"}
```

---

### مرحله ۴ — VPS: اجرای relay server

وابستگی‌ها رو نصب کن:
```bash
pip install fastapi uvicorn httpx --break-system-packages
```

با screen اجرا کن تا بعد از disconnect SSH هم بمونه:
```bash
apt install screen -y
screen -S mhr

export MHR_SECRET="یه_کلید_سری_دلخواه"
python3 ~/mhr-ggate/server/server.py &

# از screen جدا بشو: Ctrl+A بعد D
```

تست:
```bash
curl http://localhost:8080/health
# {"status":"ok","xray":"127.0.0.1:10000/mhr"}
```

---

### مرحله ۵ — گوگل: دیپلوی GAS relay

۱. برو به [script.google.com](https://script.google.com) → روی **New project** کلیک کن
۲. همه کد پیش‌فرض رو پاک کن
۳. فایل `gas/Code.gs` از ریپو رو باز کن، همه رو کپی کن، توی ادیتور پیست کن
۴. فقط این دو خط بالا رو ویرایش کن:
```js
var VPS_URL = "https://yourdomain.com";    // دامنه VPS از مرحله ۳
var SECRET  = "یه_کلید_سری_دلخواه";       // همون کلید مرحله ۴
```
۵. روی **Deploy** (بالا راست) کلیک کن → **New deployment**
۶. روی آیکون چرخ‌دنده ⚙ کنار "type" کلیک کن → **Web app** رو انتخاب کن
۷. تنظیم کن:
   - Execute as: **Me**
   - Who has access: **Anyone**
۸. روی **Deploy** کلیک کن → **Authorize access** → حساب گوگلت رو انتخاب کن → **Allow**
۹. URL رو کپی کن — شبیه اینه:
```
https://script.google.com/macros/s/AKfycb.../exec
```
`script_id` همون قسمت طولانی بین `/s/` و `/exec` هست

---

### مرحله ۶ — ویندوز: تنظیم config

برو به پوشه `mhr-ggate`، فایل `config.example.json` رو پیدا کن:
- راست کلیک → Copy → Paste → اسمش رو بذار `config.json`
- راست کلیک روی `config.json` → Open with → Notepad

مقادیر رو پر کن:
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

- `google_ip` — همون پیش‌فرض بذار. یا از IPهای وایت‌لیست Akamai استفاده کن.
- `front_domain` — همون `www.google.com` بذار
- `script_id` — ID طولانی از URL دیپلوی GAS (بین `/s/` و `/exec`)
- `auth_key` — همون کلید سری از مراحل ۴ و ۵

فایل رو ذخیره کن.

---

### مرحله ۷ — ویندوز: اجرای پروکسی

CMD رو داخل پوشه mhr-ggate باز کن:
- **Shift** رو نگه دار + راست کلیک داخل پوشه `mhr-ggate` → "Open PowerShell window here"

یا CMD رو دستی باز کن:
```cmd
cd C:\Users\YourName\mhr-ggate\client
python proxy.py -c ../config.json
```

این پنجره CMD رو باز نگه دار تا وقتی می‌خوای از پروکسی استفاده کنی. بستنش پروکسی رو قطع می‌کنه.

باید این رو ببینی:
```
  mhr-ggate | Domain Fronting Proxy
  Fronting IP   : 216.239.38.120
  SNI (DPI sees): www.google.com
  Real host     : script.google.com (inside TLS)
  SOCKS5        : 127.0.0.1:1080
```

---

### مرحله ۸ — تنظیم پروکسی

**فایرفاکس:**
Settings → سرچ "proxy" → Manual proxy → SOCKS5 → Host: `127.0.0.1` Port: `1080`

**کروم:**
افزونه [FoxyProxy](https://chrome.google.com/webstore/detail/foxyproxy/gcknhkkoolaabfmlnjonogaaifnjlfnp) رو نصب کن → Add proxy → SOCKS5 → `127.0.0.1:1080`

**سیستم ویندوز (همه برنامه‌ها):**
Settings → Network & Internet → Proxy → Manual proxy setup → روشن کن → Address: `127.0.0.1` Port: `1080`

**بازی (ویندوز):**
[Proxifier](https://www.proxifier.com/) رو دانلود کن → Profile → Proxy Servers → Add → `127.0.0.1` پورت `1080` نوع SOCKS5 → بعد بازیت رو ازش رد کن

---

## بازی آنلاین

UDP کار می‌کنه چون xudp mux توی xray، داده‌های UDP رو داخل تونل VMess رپ می‌کنه. از Proxifier روی ویندوز استفاده کن تا هر بازی رو بدون تنظیمات داخلی روت کنه.

---

## عیب‌یابی

**خطای 404 روی سرور:**
- چک کن xray در حال اجراست: `curl http://127.0.0.1:10000/mhr`
- health endpoint: `curl http://localhost:8080/health`
- مطمئن شو `XRAY_PATH=/mhr` با path توی `xray_server.json` یکیه

**خطای 403 روی سرور:**
- `auth_key` در `config.json`، `MHR_SECRET` روی VPS، و `SECRET` در `Code.gs` باید دقیقاً یه مقدار باشن

**خطای 502 روی سرور:**
- xray کرش کرده — دوباره اجرا کن: `xray run -config ~/mhr-ggate/server/xray_server.json &`

**certbot خطای unauthorized داد:**
- پروکسی Cloudflare رو خاموش کن (ابر نارنجی → خاکستری) توی DNS، ۲ دقیقه صبر کن، دوباره امتحان کن

**از ایران اصلاً وصل نمی‌شه:**
- مطمئن شو `client/proxy.py` روی PC ات در حال اجراست
- مستقیم به VPS وصل نشو

**بعد از قطع SSH همه چیز خاموش شد:**
- از screen استفاده کن تا پروسس‌ها زنده بمونن:
```bash
screen -r mhr   # دوباره وصل شو به screen session
```

**proxy.py روی ویندوز کرش می‌کنه:**
- چک کن Python نصبه: `python --version`
- اگه نصب نیست: [python.org/downloads](https://python.org/downloads) — حین نصب تیک "Add to PATH" رو بزن

---

## فایل‌ها

```
mhr-ggate/
├── client/
│   ├── fronting.py          # مغز دامین فرانتینگ (SNI swap)
│   ├── proxy.py             # پروکسی SOCKS5 لوکال — روی ویندوز اجرا کن
│   └── certs.py             # سرتیفکیشن
├── gas/
│   └── Code.gs              # پیست کن توی Google Apps Script
├── server/
│   ├── server.py            # relay bridge — روی VPS اجرا کن
│   └── xray_server.json     # کانفیگ xray — روی VPS اجرا کن
├── v2ray/
│   └── generate_config.py   # لینک vmess:// می‌سازه برای v2rayN/Hiddify
├── config.example.json      # کپی کن به config.json و پر کن
└── README.md
```

---

## نکات

- پلن رایگان GAS: ~۲۰ هزار URL fetch در روز. برای استفاده شخصی کافیه. بیشتر لازم داری؟ از یه حساب گوگل دیگه یه GAS جدید deploy کن.
- SplitHTTP نیاز به WebSocket upgrade handshake نداره — سخت‌تر fingerprint می‌شه.
- IP سرور هیچ‌وقت مستقیم دیال نمی‌شه — فقط GAS بهش وصل می‌شه. همه پورت‌ها رو فایروال کن جز ۴۴۳.

---

## کردیت‌ها

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — ایده اصلی GAS + دامین فرانتینگ
- [masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — کانسپت اصلی relay
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — تونل اصلی

---

مشارکت خوشحال می‌کنیم، PR باز.
