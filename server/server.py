#!/usr/bin/env python3
"""
mhr-ggate | VPS Relay Server
Runs on your VPS. Receives requests from GAS (via domain fronting)
and forwards them to the local xray instance.

  GAS → this server (port 8080, behind nginx) → xray (port 10000, localhost only)

Requirements:
    pip install fastapi uvicorn httpx --break-system-packages
"""

import base64
import os
import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

# ─── CONFIG ────────────────────────────────────────────────────────────────────
# Set these as environment variables or edit the defaults below
SECRET      = os.environ.get("MHR_SECRET",    "CHANGE_THIS_SECRET_KEY")
XRAY_PORT   = int(os.environ.get("XRAY_PORT", "10000"))   # xray SplitHTTP port (localhost)
XRAY_PATH   = os.environ.get("XRAY_PATH",     "/mhr")     # must match xray_server.json
LISTEN_PORT = int(os.environ.get("LISTEN_PORT","8080"))    # this server listens here (nginx proxies it)
# ───────────────────────────────────────────────────────────────────────────────

app = FastAPI(docs_url=None, redoc_url=None)
xray_base = f"http://127.0.0.1:{XRAY_PORT}"


def verify_secret(request: Request):
    """Reject requests that don't carry the correct secret header."""
    incoming = request.headers.get("X-MHR-Secret", "")
    if incoming != SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


def decode_body(raw: bytes) -> bytes:
    """GAS encodes binary bodies as base64 — decode if needed."""
    try:
        return base64.b64decode(raw)
    except Exception:
        return raw  # already raw bytes


def clean_headers(request: Request) -> dict:
    """Strip hop-by-hop and mhr-specific headers before forwarding to xray."""
    skip = {
        "host", "x-mhr-secret", "x-mhr-path",
        "content-length", "transfer-encoding", "connection",
    }
    return {k: v for k, v in request.headers.items() if k.lower() not in skip}


# ── Health check (must be defined BEFORE the catch-all route) ─────────────────
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "xray": f"127.0.0.1:{XRAY_PORT}{XRAY_PATH}"})


# ── Main relay routes ──────────────────────────────────────────────────────────
@app.post("/{path:path}")
async def relay_post(path: str, request: Request):
    verify_secret(request)

    body = decode_body(await request.body())
    headers = clean_headers(request)
    headers["Host"] = f"127.0.0.1:{XRAY_PORT}"

    target = xray_base + XRAY_PATH

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(target, content=body, headers=headers)
    except httpx.ConnectError:
        # xray is not running or wrong port
        return PlainTextResponse(
            "xray not reachable — is xray running on port {}?".format(XRAY_PORT),
            status_code=502
        )

    encoded = base64.b64encode(resp.content).decode()
    return PlainTextResponse(content=encoded, status_code=resp.status_code)


@app.get("/{path:path}")
async def relay_get(path: str, request: Request):
    verify_secret(request)

    headers = clean_headers(request)
    headers["Host"] = f"127.0.0.1:{XRAY_PORT}"

    target = xray_base + XRAY_PATH

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(target, headers=headers)
    except httpx.ConnectError:
        return PlainTextResponse(
            "xray not reachable — is xray running on port {}?".format(XRAY_PORT),
            status_code=502
        )

    encoded = base64.b64encode(resp.content).decode()
    return PlainTextResponse(content=encoded, status_code=resp.status_code)


# ── Startup banner ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def banner():
    print("=" * 55)
    print("  mhr-ggate | VPS Relay Server")
    print("=" * 55)
    print(f"  Listening on  : 0.0.0.0:{LISTEN_PORT}")
    print(f"  Forwarding to : 127.0.0.1:{XRAY_PORT}{XRAY_PATH}")
    print(f"  Secret key    : {'*' * len(SECRET)}")
    print(f"  Health check  : http://localhost:{LISTEN_PORT}/health")
    print("=" * 55)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=LISTEN_PORT)
