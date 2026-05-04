#!/usr/bin/env python3
"""
mhr-gvps | VPS Relay Server
Receives forwarded requests from GAS and proxies them to the local v2ray instance.
Run this on your VPS alongside v2ray/xray.

Requirements: pip install fastapi uvicorn httpx --break-system-packages
"""

import base64
import os
import httpx
import uvicorn
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse

# ─── CONFIG ───────────────────────────────────────────────
SECRET       = os.environ.get("MHR_SECRET", "CHANGE_THIS_SECRET_KEY")
V2RAY_PORT   = int(os.environ.get("V2RAY_PORT", "10000"))   # local v2ray SplitHTTP port
LISTEN_PORT  = int(os.environ.get("LISTEN_PORT", "8080"))   # this server's port (put behind nginx+TLS)
# ──────────────────────────────────────────────────────────

app = FastAPI(docs_url=None, redoc_url=None)
v2ray_base = f"http://127.0.0.1:{V2RAY_PORT}"


def check_secret(request: Request):
    secret = request.headers.get("X-MHR-Secret", "")
    if secret != SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/{path:path}")
async def relay_post(path: str, request: Request):
    check_secret(request)
    fwd_path = request.headers.get("X-MHR-Path", f"/{path}")
    body     = await request.body()

    # Decode base64 if GAS encoded it (GAS sends base64 for binary safety)
    try:
        body = base64.b64decode(body)
    except Exception:
        pass  # not base64, use raw

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "x-mhr-secret", "x-mhr-path",
                             "content-length", "transfer-encoding")
    }
    headers["Host"] = f"127.0.0.1:{V2RAY_PORT}"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{v2ray_base}{fwd_path}",
            content=body,
            headers=headers,
        )
        encoded = base64.b64encode(resp.content).decode()
        return PlainTextResponse(content=encoded, status_code=resp.status_code)


@app.get("/{path:path}")
async def relay_get(path: str, request: Request):
    check_secret(request)
    fwd_path = request.headers.get("X-MHR-Path", f"/{path}")

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "x-mhr-secret", "x-mhr-path")
    }
    headers["Host"] = f"127.0.0.1:{V2RAY_PORT}"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{v2ray_base}{fwd_path}",
            headers=headers,
        )
        encoded = base64.b64encode(resp.content).decode()
        return PlainTextResponse(content=encoded, status_code=resp.status_code)


@app.get("/")
async def health():
    return PlainTextResponse("ok")


if __name__ == "__main__":
    print(f"[*] mhr-gvps server starting on 0.0.0.0:{LISTEN_PORT}")
    print(f"[*] Bridging GAS → this server → v2ray on port {V2RAY_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=LISTEN_PORT)
