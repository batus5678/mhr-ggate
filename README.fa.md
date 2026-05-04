# mhr-ggate

> 🇬🇧 [English README](README.md)

ترافیک رو از طریق Google Apps Script به VPS خودت هدایت می‌کنه، به جای Cloudflare Workers. بر اساس [mhr-cfw](https://github.com/denuitt1/mhr-cfw) ساخته شده ولی یه تونل واقعی xray داره — یعنی UDP و بازی آنلاین هم کار می‌کنه.

```
شما ← script.google.com ← VPS شما ← اینترنت
```

GAS روی دامنه‌ی گوگل اجرا می‌شه و عملاً هیچ‌وقت فیلتر نمی‌شه. VPS شما مخفی می‌مونه و هیچ‌کس مستقیم بهش وصل نمی‌شه.

---

## چه فرقی با mhr-cfw داره

mhr-cfw از Cloudflare Workers به عنوان بک‌اند استفاده می‌کنه و فقط ترافیک خام رو HTTP-پروکسی می‌کنه. به همین خاطره که بازی‌ها کار نمی‌کنن و اکثر اپ‌ها خراب می‌شن — تونل واقعی وجود نداره.

mhr-ggate یه xray روی VPS شما نصب می‌کنه با VMess + SplitHTTP. GAS درخواست‌ها رو به relay server می‌فرسته، relay هم به xray وصل می‌شه. تونل کامل، با پشتیبانی از UDP.

| | mhr-cfw | mhr-ggate |
|---|---|---|
| فرانت‌اند | GAS | GAS |
| بک‌اند | Cloudflare Workers | VPS شخصی |
| بازی / UDP | ✖ | ✔ |
| پروتکل | HTTP proxy ساده | VMess + SplitHTTP |
| هزینه بک‌اند | رایگان | ~۳-۵ دلار ماهانه |
| کنترل بک‌اند | ✖ | ✔ |

---

## نیازمندی‌ها

- یه VPS خارج از ایران (هر پروایدری)
- یه حساب گوگل (رایگان)
- [xray-core](https://github.com/XTLS/Xray-core) روی VPS
- Python 3.10+ روی VPS
- v2rayN / NekoBox / Hiddify روی دستگاهت

---

## راه‌اندازی

### ۱. کلون کردن

```bash
git clone https://github.com/Vuks1n/mhr-ggate
cd mhr-ggate
```

### ۲. نصب xray روی VPS

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

یه UUID بساز و نگهش دار:

```bash
xray uuid
```

### ۳. تنظیم xray server

فایل `server/xray_server.json` رو باز کن و UUID رو جایگزین کن:

```json
"id": "UUID-خودت-رو-اینجا-بذار"
```

اجرا کن:

```bash
xray run -config server/xray_server.json
```

xray روی `127.0.0.1:10000` گوش می‌ده — از اینترنت دسترسی نداره.

### ۴. اجرای relay server

```bash
pip install fastapi uvicorn httpx

export MHR_SECRET="یه_کلید_سری_انتخاب_کن"
python3 server/server.py
```

پشت nginx + TLS روی پورت ۴۴۳ بذارش:

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

دامنه نداری؟ سرتیفیکت self-signed با IP مستقیم هم کار می‌کنه.

### ۵. دیپلوی GAS relay

۱. برو به [script.google.com](https://script.google.com) ← New Project  
۲. محتوای `gas/Code.gs` رو پیست کن  
۳. بالای فایل رو ویرایش کن:

```js
var VPS_URL = "https://yourdomain.com";
var SECRET  = "یه_کلید_سری_انتخاب_کن";   // همون مقدار مرحله ۴
```

۴. Deploy ← New Deployment ← Web App
   - Execute as: **Me**
   - Who has access: **Anyone**

۵. لینک دیپلوی رو کپی کن:
```
https://script.google.com/macros/s/XXXXXXXXXX/exec
```

### ۶. ساخت کانفیگ کلاینت

```bash
python3 v2ray/generate_config.py \
  --gas-url "https://script.google.com/macros/s/XXXXXXXXXX/exec" \
  --uuid    "UUID-خودت"
```

یه فایل `client_config.json` و یه لینک `vmess://` می‌سازه که می‌تونی مستقیم توی کلاینت v2ray پیستش کنی.

---

## اتصال

```bash
# روش A — xray CLI
xray run -config v2ray/client_config.json

# روش B — لینک vmess:// رو توی v2rayN، NekoBox یا Hiddify پیست کن
```

پروکسی‌های لوکال بعد از اتصال:
- SOCKS5: `127.0.0.1:1080`
- HTTP: `127.0.0.1:8118`

---

## بازی آنلاین

کلاینت بازی یا لانچر رو روی SOCKS5 `127.0.0.1:1080` تنظیم کن.

روی ویندوز می‌تونی از [Proxifier](https://www.proxifier.com/) استفاده کنی تا هر بازی‌ای رو بدون نیاز به تنظیمات داخلی پروکسی روت کنه.

UDP کار می‌کنه چون xudp mux توی xray، داده‌های UDP رو داخل تونل VMess رپ می‌کنه.

---

## فایل‌ها

```
mhr-ggate/
├── gas/
│   └── Code.gs              # پیست کن توی Google Apps Script
├── server/
│   ├── server.py            # relay server، روی VPS اجرا می‌شه
│   └── xray_server.json     # کانفیگ xray برای VPS
├── v2ray/
│   └── generate_config.py   # کانفیگ کلاینت و لینک vmess:// می‌سازه
└── README.md
```

---

## نکات

- پلن رایگان GAS روزانه حدود ۲۰ هزار URL fetch داره که برای استفاده شخصی کافیه. اگه بیشتر لازم داشتی، از یه حساب گوگل دوم با یه GAS جداگانه استفاده کن.
- SplitHTTP نیاز به WebSocket upgrade handshake نداره، پس fingerprint کردنش سخت‌تره.
- IP سرور هیچ‌وقت مستقیم از طرف کلاینت دیال نمی‌شه — فقط GAS بهش وصل می‌شه. پورت relay رو فایروال کن و فقط ۴۴۳ رو از طریق nginx باز بذار.

---

## کردیت‌ها

- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — ایده اصلی GAS به CF Workers
- [XTLS/Xray-core](https://github.com/XTLS/Xray-core) — تونل اصلی

---

مشارکت خوشحال می‌کنیم، PR باز.
