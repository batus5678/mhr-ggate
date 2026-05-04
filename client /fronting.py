"""
mhr-ggate | Domain Fronting Core
---------------------------------
How it works:
  1. TCP connect  → google_ip (e.g. 216.239.38.120)  — a real Google CDN IP
  2. TLS SNI      → front_domain (e.g. www.google.com) — what DPI sees
  3. HTTP Host    → script.google.com                  — what Google routes internally

Iran's DPI sees: connection to Google IP + SNI www.google.com = normal Google traffic
Google internally: routes based on Host header → GAS deployment → your VPS
"""

import ssl
import socket
import urllib.parse
import base64
import json
import logging
from typing import Optional

log = logging.getLogger("DomainFront")


class DomainFrontClient:
    """
    Sends requests through domain fronting:
      - Connects to a CDN IP (TCP level)
      - Uses an allowed domain as TLS SNI
      - Puts the real GAS host in the HTTP Host header (inside TLS, invisible to DPI)
    """

    def __init__(self, config: dict):
        self.google_ip     = config.get("google_ip", "216.239.38.120")
        self.front_domain  = config.get("front_domain", "www.google.com")
        self.script_id     = config.get("script_id", "")
        self.auth_key      = config.get("auth_key", "")
        self.verify_ssl    = config.get("verify_ssl", True)
        self.timeout       = config.get("timeout", 30)

        # The real GAS host — goes inside encrypted TLS, DPI cannot see it
        self.gas_host      = "script.google.com"
        self.gas_path      = f"/macros/s/{self.script_id}/exec"

    def _make_tls_socket(self) -> ssl.SSLSocket:
        """
        Open a TCP connection to google_ip but complete TLS handshake
        with front_domain as SNI. This is the core of domain fronting.
        """
        ctx = ssl.create_default_context()
        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        raw = socket.create_connection((self.google_ip, 443), timeout=self.timeout)

        # SNI = front_domain → DPI sees www.google.com
        tls = ctx.wrap_socket(raw, server_hostname=self.front_domain)
        log.debug("TLS handshake OK: IP=%s SNI=%s", self.google_ip, self.front_domain)
        return tls

    def _build_http_request(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        extra_headers: dict = None,
    ) -> bytes:
        """
        Build a raw HTTP/1.1 request.
        Host header = gas_host (script.google.com) — inside TLS, invisible to DPI.
        """
        headers = {
            "Host": self.gas_host,          # real destination, hidden inside TLS
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(body)),
            "Connection": "close",
            "X-MHR-Auth": self.auth_key,
        }
        if extra_headers:
            headers.update(extra_headers)

        header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
        request_line = f"{method} {path} HTTP/1.1"
        raw = f"{request_line}\r\n{header_lines}\r\n\r\n".encode() + body
        return raw

    def _read_http_response(self, sock: ssl.SSLSocket) -> tuple[int, bytes]:
        """Read a full HTTP response, return (status_code, body)."""
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        # Split headers and body
        if b"\r\n\r\n" not in data:
            return 0, data

        header_part, body = data.split(b"\r\n\r\n", 1)
        status_line = header_part.split(b"\r\n")[0].decode(errors="replace")

        try:
            status_code = int(status_line.split(" ")[1])
        except (IndexError, ValueError):
            status_code = 0

        # GAS returns base64-encoded binary — decode it
        try:
            body = base64.b64decode(body.strip())
        except Exception:
            pass  # not base64, return raw

        return status_code, body

    def post(self, payload: bytes, target_path: str = "/") -> tuple[int, bytes]:
        """
        POST payload through domain fronting → GAS → your VPS.
        target_path is passed as a query param so GAS knows where to forward.
        """
        path = self.gas_path + "?path=" + urllib.parse.quote(target_path)
        # Encode payload as base64 so it survives GAS's HTTP handling
        encoded = base64.b64encode(payload)

        try:
            sock = self._make_tls_socket()
            request = self._build_http_request(
                "POST",
                path,
                body=encoded,
                extra_headers={"X-MHR-Path": target_path},
            )
            sock.sendall(request)
            status, body = self._read_http_response(sock)
            sock.close()
            log.debug("POST %s → %d (%d bytes)", target_path, status, len(body))
            return status, body
        except Exception as e:
            log.error("Domain fronting POST failed: %s", e)
            return 0, b""

    def get(self, target_path: str = "/") -> tuple[int, bytes]:
        """GET through domain fronting."""
        path = self.gas_path + "?path=" + urllib.parse.quote(target_path)
        try:
            sock = self._make_tls_socket()
            request = self._build_http_request(
                "GET",
                path,
                extra_headers={"X-MHR-Path": target_path},
            )
            sock.sendall(request)
            status, body = self._read_http_response(sock)
            sock.close()
            log.debug("GET %s → %d (%d bytes)", target_path, status, len(body))
            return status, body
        except Exception as e:
            log.error("Domain fronting GET failed: %s", e)
            return 0, b""
