"""
mhr-ggate | Client Relay  (NEW — v2)
=====================================
Sits between your LOCAL xray process and the GAS relay.

WHY THIS EXISTS
---------------
xray's xhttp outbound sends raw VMess-encrypted bytes inside HTTP POST bodies.
Those bytes are arbitrary binary.  Google Apps Script's UrlFetchApp cannot
forward arbitrary binary payloads reliably — it treats the body as a UTF-8
string, which corrupts non-ASCII bytes.

The fix: wrap every outgoing body in base64 BEFORE it hits GAS, and unwrap
every incoming response.  This relay does that wrapping transparently so xray
and the VPS server.py never need to change their binary expectations.

ARCHITECTURE
------------
    local xray (SOCKS5 in, xhttp out → 127.0.0.1:RELAY_PORT)
        │   HTTP POST with raw VMess bytes in body
        ▼
    client_relay.py  ← YOU ARE HERE
        │   base64-encodes body → calls fronting.DomainFrontClient.post()
        ▼
    Google CDN IP (SNI: www.google.com — what Iran's DPI sees)
        │   inside TLS: Host: script.google.com
        ▼
    GAS relay (Code.gs)
        │   forwards base64 string to VPS
        ▼
    server.py  →  VPS xray (xhttp inbound, packet-up)  →  internet

Run (from the client/ directory):
    python3 client_relay.py -c ../config.json

Then point your local xray xhttp outbound at 127.0.0.1:<relay_port>.
"""

import asyncio
import base64
import json
import logging
import argparse
import sys
from pathlib import Path

# Allow running from project root or client/ directory
sys.path.insert(0, str(Path(__file__).parent))
from fronting import DomainFrontClient

log = logging.getLogger("ClientRelay")

# Maximum body size accepted from local xray (sanity guard)
MAX_BODY = 10 * 1024 * 1024  # 10 MB


class ClientRelay:
    def __init__(self, config: dict):
        self.host    = config.get("listen_host", "127.0.0.1")
        self.port    = int(config.get("relay_port", 10002))
        self.fronter = DomainFrontClient(config)

    # ── Connection handler ────────────────────────────────────────────────────

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername", ("?", 0))
        try:
            await self._process(reader, writer, peer)
        except Exception as exc:
            log.debug("Handler error from %s:%s — %s", *peer, exc)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _process(self, reader, writer, peer):
        # Read the full HTTP request that xray sends (xhttp transport).
        # xray sends a short self-contained POST per packet-up mode — we don't
        # need to handle chunked or keep-alive here.
        raw = b""
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=30)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > MAX_BODY:
                    log.warning("Oversized payload from %s:%s (%d B) — dropping", *peer, len(raw))
                    self._send_response(writer, b"", 413)
                    return
                # Stop reading once we have a complete HTTP message
                # (headers + body according to Content-Length)
                if b"\r\n\r\n" in raw:
                    header_part, body_so_far = raw.split(b"\r\n\r\n", 1)
                    cl = _parse_content_length(header_part)
                    if cl is not None and len(body_so_far) >= cl:
                        raw = header_part + b"\r\n\r\n" + body_so_far[:cl]
                        break
        except asyncio.TimeoutError:
            pass

        if not raw:
            return

        # Parse HTTP request
        body, path = _split_http(raw)

        log.debug("Relaying %d B (path=%s) from %s:%s", len(body), path, *peer)

        # Forward through domain fronting (fronting.py handles the base64 wrap)
        loop = asyncio.get_event_loop()
        try:
            status, response_body = await loop.run_in_executor(
                None, self.fronter.post, body, path
            )
        except Exception as exc:
            log.error("Domain fronting error: %s", exc)
            self._send_response(writer, b"", 502)
            return

        if status == 0:
            log.warning("Relay returned status 0 (fronting failed)")
            self._send_response(writer, b"", 502)
            return

        # response_body is already decoded by fronting.py — raw VMess bytes
        log.debug("Response %d B from relay (HTTP %d)", len(response_body), status)
        self._send_response(writer, response_body, 200)
        await writer.drain()

    @staticmethod
    def _send_response(writer, body: bytes, status: int) -> None:
        reason = {200: "OK", 413: "Payload Too Large", 502: "Bad Gateway"}.get(status, "Error")
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        writer.write(header + body)

    # ── Server ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        server = await asyncio.start_server(self.handle, self.host, self.port)
        addrs  = [s.getsockname() for s in server.sockets]
        log.info("Client relay listening on %s", addrs)
        async with server:
            await server.serve_forever()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _split_http(raw: bytes) -> tuple[bytes, str]:
    """Return (body_bytes, request_path) from a raw HTTP/1.1 message."""
    if b"\r\n\r\n" not in raw:
        return raw, "/mhr"
    header_part, body = raw.split(b"\r\n\r\n", 1)
    first_line = header_part.split(b"\r\n")[0].decode(errors="replace")
    parts = first_line.split()
    path  = parts[1] if len(parts) >= 2 else "/mhr"
    # Strip query string if any
    path  = path.split("?")[0] or "/mhr"
    return body, path


def _parse_content_length(header_part: bytes) -> int | None:
    for line in header_part.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            try:
                return int(line.split(b":", 1)[1].strip())
            except ValueError:
                pass
    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="mhr-ggate client relay — wraps xhttp traffic for GAS transit"
    )
    parser.add_argument("-c", "--config",    default="../config.json",
                        help="Path to config.json (default: ../config.json)")
    parser.add_argument("--log-level",       default=None,
                        help="Override log level (DEBUG/INFO/WARNING)")
    args = parser.parse_args()

    try:
        with open(args.config) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"[!] Config not found: {args.config}")
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"[!] Config JSON error: {exc}")
        sys.exit(1)

    level = args.log_level or config.get("log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    relay_port = config.get("relay_port", 10002)
    print("=" * 60)
    print("  mhr-ggate | Client Relay")
    print("=" * 60)
    print(f"  Listen addr : {config.get('listen_host', '127.0.0.1')}:{relay_port}")
    print(f"  Fronting IP : {config.get('google_ip', '216.239.38.120')}")
    print(f"  SNI (DPI)   : {config.get('front_domain', 'www.google.com')}")
    print(f"  Real host   : script.google.com (hidden inside TLS)")
    print()
    print(f"  Point xray outbound → 127.0.0.1:{relay_port}  (xhttp, packet-up)")
    print("=" * 60)

    try:
        asyncio.run(ClientRelay(config).start())
    except KeyboardInterrupt:
        print("\n[*] Stopped.")


if __name__ == "__main__":
    main()
