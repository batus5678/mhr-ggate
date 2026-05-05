"""
mhr-ggate | VPS Relay Server  (v2 — fixed & hardened)

Fixes vs original:
  - Python indentation was broken (SyntaxError on import).
  - Secret check is now constant-time (hmac.compare_digest) — prevents timing attacks.
  - Payload size limited to MAX_PAYLOAD bytes — prevents OOM on malformed requests.
  - /health and /_mhr/stats endpoints for monitoring.
  - Structured logging with timestamps.
  - Graceful 400 / 502 / 500 responses with log context.
  - All config driven by environment variables (MHR_SECRET, XRAY_HOST, XRAY_PORT,
    XRAY_PATH, PORT) so secrets never live in source code.

Run:
  export MHR_SECRET="your_secret"
  export XRAY_PORT=10000
  export XRAY_PATH=/mhr
  python3 server/server.py

Dependencies:
  pip install fastapi uvicorn httpx --break-system-packages
"""

import base64
import hmac
import logging
import os
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

# ── Config ───────────────────────────────────────────────────────────────────

SECRET      = os.environ.get("MHR_SECRET", "YOUR_SECRET_KEY")
XRAY_HOST   = os.environ.get("XRAY_HOST", "127.0.0.1")
XRAY_PORT   = int(os.environ.get("XRAY_PORT", 10000))
XRAY_PATH   = os.environ.get("XRAY_PATH", "/mhr")
XRAY_URL    = f"http://{XRAY_HOST}:{XRAY_PORT}{XRAY_PATH}"
SERVER_PORT = int(os.environ.get("PORT", 8080))
MAX_PAYLOAD = 10 * 1024 * 1024   # 10 MB hard ceiling

START_TIME  = time.time()
REQUEST_COUNT = 0
BYTE_COUNT    = 0

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mhr-server")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(docs_url=None, redoc_url=None)


def _check_secret(given: str) -> bool:
    """Constant-time comparison — prevents timing side-channel attacks."""
    return hmac.compare_digest(
        (given or "").encode(),
        SECRET.encode(),
    )


# ── Health / stats ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({
        "status"  : "ok",
        "xray"    : f"{XRAY_HOST}:{XRAY_PORT}{XRAY_PATH}",
        "uptime_s": round(time.time() - START_TIME),
    })


@app.get("/_mhr/stats")
async def stats():
    return JSONResponse({
        "uptime_s"     : round(time.time() - START_TIME),
        "requests"     : REQUEST_COUNT,
        "bytes_relayed": BYTE_COUNT,
        "xray_url"     : XRAY_URL,
    })


# ── Relay ─────────────────────────────────────────────────────────────────────

@app.post("/{path:path}")
async def relay(request: Request, path: str):
    global REQUEST_COUNT, BYTE_COUNT

    # ── Auth ─────────────────────────────────────────────────────────────────
    if not _check_secret(request.headers.get("X-MHR-Secret", "")):
        log.warning("Rejected unauthenticated request from %s",
                    request.client.host if request.client else "?")
        return PlainTextResponse("Forbidden", status_code=403)

    # ── Read body ─────────────────────────────────────────────────────────────
    raw = await request.body()
    if len(raw) > MAX_PAYLOAD:
        log.warning("Payload too large: %d bytes from %s", len(raw),
                    request.client.host if request.client else "?")
        return PlainTextResponse("Payload Too Large", status_code=413)

    # ── Decode base64 from GAS ────────────────────────────────────────────────
    # The client (fronting.py) base64-encodes the VMess/xhttp bytes before
    # sending them to GAS, and GAS passes that base64 string straight through
    # (no re-encoding in the fixed Code.gs).  We decode it here to get the
    # original binary bytes that xray expects.
    try:
        body = base64.b64decode(raw)
    except Exception as exc:
        log.error("base64 decode failed (%s) — raw snippet: %r", exc, raw[:64])
        return PlainTextResponse("Bad Request: invalid base64", status_code=400)

    # ── Forward to xray ───────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(XRAY_URL, content=body)

        REQUEST_COUNT += 1
        BYTE_COUNT    += len(body)
        log.info("Relayed %d B → xray → %d B response (status %d)",
                 len(body), len(resp.content), resp.status_code)

        # Encode xray's binary response as base64 so it survives the GAS round-trip
        # back to the client.  fronting.py will decode it on the other end.
        return PlainTextResponse(base64.b64encode(resp.content).decode())

    except httpx.ConnectError:
        log.error("Cannot reach xray at %s — is xray running?", XRAY_URL)
        return PlainTextResponse("Bad Gateway: xray unreachable", status_code=502)

    except httpx.TimeoutException:
        log.error("Timeout waiting for xray at %s", XRAY_URL)
        return PlainTextResponse("Gateway Timeout", status_code=504)

    except Exception as exc:
        log.exception("Unexpected relay error: %s", exc)
        return PlainTextResponse("Internal Server Error", status_code=500)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("mhr-ggate server starting on 0.0.0.0:%d", SERVER_PORT)
    log.info("Xray endpoint: %s", XRAY_URL)
    if SECRET == "YOUR_SECRET_KEY":
        log.warning("⚠  MHR_SECRET is still the default — set it in your environment!")
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")
