# mhr-ggate

> 🇬🇧 [English README](README.md)

> **هدف:** ابزار متن‌باز برای مطالعه پروتکل‌های رمزگذاری و دور زدن سانسور.  
> فقط برای استفاده شخصی، آموزشی و پژوهشی.

ترافیک رو از طریق **دامین فرانتینگ → Google Apps Script → VPS → xray** هدایت می‌کنه.  
بازی آنلاین و UDP هم پشتیبانی می‌شن.

```
دستگاه شما
  └─► Google CDN IP  (فیلترینگ می‌بینه: www.google.com ✔)
        └─► script.google.com  (داخل TLS مخفیه)
              └─► GAS relay
                    └─► VPS شما  (server.py)
                          └─► xray  (VMess + xhttp، packet-up)
                                └─► اینترنت / سرور بازی
```

---

## نسخه ۲ — باگ‌های رفع شده

| مشکل | دلیل | راه‌حل |
|---|---|---|
| باینری VMess خراب می‌شد | `e.postData.contents` بایت‌ها را به عنوان رشته UTF-8 می‌خوند | کلاینت قبل از ارسال base64 می‌کنه؛ GAS رشته ASCII رو بدون تغییر پاس می‌ده |
| دوبار base64 شدن | `Code.gs` قدیمی روی پاسخی که `server.py` قبلاً انکد کرده بود دوباره `base64Encode` صدا می‌زد | رمزگذاری دوم حذف شد — GAS مستقیم `getContentText()` برمی‌گردونه |
| محدودیت ۶ دقیقه‌ای GAS | SplitHTTP یک جریان طولانی بود | تغییر به `xhttp` با `mode: "packet-up"` — هر درخواست کوتاه و مستقله |
| حمله زمان‌بندی روی بررسی secret | مقایسه ساده رشته | جایگزینی با `hmac.compare_digest()` |
| خطای SyntaxError در `server.py` | تورفتگی اشتباه | بازنویسی کامل |
| هیچ error handling‌ای نبود | payload بد یا خرابی xray باعث exception می‌شد | پاسخ‌های 400/502/504 با لاگ ساختاریافته |
| خرابی باینری در مسیر relay | xhttp لوکال xray بایت‌های خام به GAS می‌فرستاد | `client_relay.py` جدید درخواست‌های HTTP xray رو می‌گیره و body رو base64 می‌کنه |

---

## چی کجا اجرا می‌شه

| قسمت | کجا | فایل |
|---|---|---|
| **Client Relay** *(جدید)* | دستگاه شما | `client/client_relay.py` |
| هسته دامین فرانتینگ | دستگاه شما | `client/fronting.py` |
| پروکسی MITM *(مرورگر)* | دستگاه شما | `client/proxy.py` |
| رله GAS | سرورهای گوگل (رایگان) | `gas/Code.gs` |
| سرور رله | VPS شما | `server/server.py` |
| تونل xray | VPS شما | `server/xray_server.json` |

---

## نیازمندی‌ها

| کجا | چی |
|---|---|
| دستگاه شما | Python 3.10+، xray-core *(اختیاری، برای بازی)* |
| VPS | Python 3.10+، xray-core، nginx |
| گوگل | یه حساب گوگل (رایگان) |

---

## راه‌اندازی

### مرحله 0 — کلون repo

**تو سرور**
```cmd
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

### مرحله ۱ — VPS: نصب xray-core

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
xray uuid
# مثال: 550e8400-e29b-41d4-a716-446655440000
```

UUID رو نگه دار — توی همه کانفیگ‌ها لازمته.

---

### مرحله ۲ — VPS: کانفیگ xray

فایل `server/xray_server.json` رو ویرایش کن و UUID رو پیست کن:

```json
"id": "550e8400-e29b-41d4-a716-446655440000"
```

```bash
xray run -config /path/to/server/xray_server.json
# روی 127.0.0.1:10000 گوش می‌ده — فقط localhost
```

---

### مرحله ۳ — VPS: سرور رله

```bash
pip install fastapi uvicorn httpx --break-system-packages

export MHR_SECRET="یه_کلید_سری_دلخواه"
export XRAY_PORT=10000
export XRAY_PATH=/mhr

python3 server/server.py
# روی 0.0.0.0:8080 شروع می‌کنه
```

تست:

```bash
curl http://localhost:8080/health
# {"status":"ok","xray":"127.0.0.1:10000/mhr","uptime_s":5}
```

---

### مرحله ۴ — VPS: nginx + TLS

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_read_timeout 60s;
    }
}
```

```bash
certbot --nginx -d yourdomain.com
nginx -t && systemctl reload nginx
```

---

### مرحله ۵ — گوگل: دیپلوی GAS

۱. برو به [script.google.com](https://script.google.com) ← **New project**  
۲. کد پیش‌فرض رو پاک کن، محتوای `gas/Code.gs` رو پیست کن  
۳. دو خط اول رو ویرایش کن:

```js
var VPS_URL = "https://yourdomain.com";
var SECRET  = "یه_کلید_سری_دلخواه";
```

۴. **Deploy ← New deployment** ← Web app ← Execute as: Me ← Anyone  
۵. لینک deployment رو کپی کن — `script_id` قسمت بین `/s/` و `/exec` هست

---

### مرحله ۶ — دستگاه شما: config.json

```bash
cp config.example.json config.json
```

```json
{
  "google_ip":    "216.239.38.120",
  "front_domain": "www.google.com",
  "script_id":    "AKfycb...",
  "auth_key":     "یه_کلید_سری_دلخواه",
  "listen_host":  "127.0.0.1",
  "socks5_port":  1080,
  "listen_port":  8085,
  "relay_port":   10002,
  "log_level":    "INFO"
}
```

---

### مرحله ۷ — دستگاه شما: شروع

**ویندوز (پیشنهادی):** روی `start.bat` دوبار کلیک کن — deps رو نصب می‌کنه، config رو چک می‌کنه، و لانچر GUI رو باز می‌کنه.

**خط فرمان (هر سیستم‌عاملی):**

ترمینال ۱ — Client relay (برای مسیر xray ضروریه):

```bash
cd client
python3 client_relay.py -c ../config.json
```

ترمینال ۲ — xray لوکال (برای SOCKS5 / بازی):

```bash
# ابتدا UUID خودت رو در client/xray_client.json پیست کن
xray run -config client/xray_client.json
```

پروکسی سیستم رو روی **SOCKS5 `127.0.0.1:1080`** تنظیم کن.

ترمینال ۳ — پروکسی MITM (فقط مرورگر، جایگزین xray):

```bash
cd client
python3 proxy.py -c ../config.json
```

پروکسی مرورگر رو روی **HTTP `127.0.0.1:8085`** تنظیم کن.

---

## نصب یک‌خطی VPS

```bash
export MHR_SECRET="کلید_سری_تو"
export MHR_DOMAIN="yourdomain.com"
bash install.sh
```

xray، deps، systemd، nginx، و certbot رو به صورت خودکار تنظیم می‌کنه.

---

## بازی آنلاین

لانچر بازیت رو روی SOCKS5 `127.0.0.1:1080` تنظیم کن.  
روی ویندوز از [Proxifier](https://www.proxifier.com/) استفاده کن تا هر بازی رو بدون تنظیمات داخلی روت کنه.  
UDP کار می‌کنه چون xray، UDP رو داخل تونل VMess رپ می‌کنه.

---

## عیب‌یابی

**خطای ۴۰۴:** xray رو چک کن (`curl http://127.0.0.1:10000/mhr`) و مطمئن شو `XRAY_PATH` با `xhttpSettings.path` یکیه.

**خطای ۴۰۳:** `auth_key`، `MHR_SECRET`، و `SECRET` باید هر سه یه مقدار باشن.

**خطای ۵۰۲:** xray روی VPS در حال اجرا نیست.

**GAS_ERR در لاگ:** GAS نتونسته به VPS وصل بشه — `VPS_URL` در `Code.gs` رو چک کن.

**خروجی باینری خراب:** مطمئن شو از `Code.gs` نسخه ۲ استفاده می‌کنی — نسخه قدیمی دوبار base64 می‌کرد.

**از ایران اصلاً وصل نمی‌شه:** `client_relay.py` رو اجرا کن و مطمئن شو xray لوکال به `127.0.0.1:10002` وصله. مستقیم به VPS وصل نشو.

---

## نکات

پلن رایگان GAS: ~۲۰ هزار URL fetch در روز — برای استفاده شخصی کافیه.  
`xhttp` با `mode: "packet-up"`: هر درخواست کوتاه و مستقله — محدودیت ۶ دقیقه‌ای GAS مشکلی ایجاد نمی‌کنه.  
IP سرور هرگز مستقیم دیال نمی‌شه — فقط GAS بهش وصل می‌شه. همه پورت‌ها رو جز ۴۴۳ فایروال کن.

---

## کردیت‌ها

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — ایده اصلی GAS + دامین فرانتینگ
- [masterking32/MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — کانسپت relay
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — موتور تونل

---

مشارکت خوشحال می‌کنیم، PR باز.
