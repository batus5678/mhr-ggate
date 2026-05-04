"""
mhr-ggate | Local Proxy
------------------------
Sits on localhost, accepts SOCKS5 + HTTP proxy connections,
tunnels everything through domain fronting → GAS → your VPS → xray.

Usage:
    python3 client/proxy.py -c config.json
"""

import asyncio
import base64
import json
import logging
import os
import sys
import argparse

from fronting import DomainFrontClient

log = logging.getLogger("Proxy")


# ─── SOCKS5 constants ─────────────────────────────────────────────────
SOCKS5_VERSION  = 0x05
SOCKS5_NOAUTH   = 0x00
SOCKS5_CONNECT  = 0x01
SOCKS5_IPV4     = 0x01
SOCKS5_DOMAIN   = 0x03
SOCKS5_IPV6     = 0x04
SOCKS5_SUCCESS  = 0x00


class ProxyServer:
    def __init__(self, config: dict):
        self.config      = config
        self.host        = config.get("listen_host", "127.0.0.1")
        self.http_port   = config.get("listen_port", 8085)
        self.socks5_port = config.get("socks5_port", 1080)
        self.fronter     = DomainFrontClient(config)

    # ──────────────────────────────────────────────────────────────────
    # Domain fronting relay
    # ──────────────────────────────────────────────────────────────────

    async def _relay_through_front(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        target_host: str,
        target_port: int,
    ):
        """
        Relay a TCP stream through domain fronting → GAS → VPS → xray.
        Reads chunks from the client, POSTs them via domain fronting,
        and writes responses back.
        """
        target_path = f"/{target_host}/{target_port}"
        log.info("Relaying %s:%d via domain fronting", target_host, target_port)

        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(65536), timeout=30)
                except asyncio.TimeoutError:
                    break
                if not data:
                    break

                # POST through domain fronting
                loop = asyncio.get_event_loop()
                status, body = await loop.run_in_executor(
                    None, self.fronter.post, data, target_path
                )

                if status == 0:
                    log.warning("Domain fronting relay failed for %s:%d", target_host, target_port)
                    break

                if body:
                    writer.write(body)
                    await writer.drain()

        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    # ──────────────────────────────────────────────────────────────────
    # SOCKS5
    # ──────────────────────────────────────────────────────────────────

    async def _handle_socks5(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Greeting
            header = await reader.readexactly(2)
            n_methods = header[1]
            await reader.readexactly(n_methods)
            writer.write(bytes([SOCKS5_VERSION, SOCKS5_NOAUTH]))
            await writer.drain()

            # Request
            req = await reader.readexactly(4)
            cmd, atyp = req[1], req[3]

            if cmd != SOCKS5_CONNECT:
                writer.write(bytes([SOCKS5_VERSION, 0x07, 0x00, 0x01, 0,0,0,0, 0,0]))
                writer.close()
                return

            if atyp == SOCKS5_IPV4:
                addr_bytes = await reader.readexactly(4)
                host = ".".join(str(b) for b in addr_bytes)
            elif atyp == SOCKS5_DOMAIN:
                length = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(length)).decode()
            elif atyp == SOCKS5_IPV6:
                addr_bytes = await reader.readexactly(16)
                import socket
                host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
            else:
                writer.close()
                return

            port_bytes = await reader.readexactly(2)
            port = int.from_bytes(port_bytes, "big")

            # Reply success
            writer.write(bytes([SOCKS5_VERSION, SOCKS5_SUCCESS, 0x00, 0x01, 0,0,0,0, 0,0]))
            await writer.drain()

            log.info("[SOCKS5] CONNECT %s:%d", host, port)
            await self._relay_through_front(reader, writer, host, port)

        except Exception as e:
            log.debug("SOCKS5 handler error: %s", e)
            try:
                writer.close()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # HTTP proxy (CONNECT method)
    # ──────────────────────────────────────────────────────────────────

    async def _handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            first_line = await reader.readline()
            line = first_line.decode(errors="replace").strip()
            parts = line.split(" ")

            if parts[0].upper() == "CONNECT":
                # HTTPS tunneling
                host_port = parts[1]
                host, port_str = host_port.rsplit(":", 1)
                port = int(port_str)

                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()

                log.info("[HTTP] CONNECT %s:%d", host, port)
                await self._relay_through_front(reader, writer, host, port)

            else:
                # Plain HTTP request — relay as-is
                if len(parts) >= 2:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(parts[1])
                    host = parsed.hostname or ""
                    port = parsed.port or 80
                    rest = await reader.read(65536)
                    full_request = first_line + rest

                    log.info("[HTTP] %s %s:%d", parts[0], host, port)
                    await self._relay_through_front(
                        asyncio.StreamReader(), writer, host, port
                    )
                writer.close()

        except Exception as e:
            log.debug("HTTP handler error: %s", e)
            try:
                writer.close()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # Detect protocol and dispatch
    # ──────────────────────────────────────────────────────────────────

    async def _dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            first_byte = await reader.read(1)
            if not first_byte:
                writer.close()
                return

            # Peek at first byte to detect protocol
            reader._buffer = bytearray(first_byte) + reader._buffer  # type: ignore

            if first_byte == b"\x05":
                await self._handle_socks5(reader, writer)
            else:
                await self._handle_http(reader, writer)
        except Exception as e:
            log.debug("Dispatch error: %s", e)
            try:
                writer.close()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────
    # Start
    # ──────────────────────────────────────────────────────────────────

    async def start(self):
        server = await asyncio.start_server(
            self._dispatch, self.host, self.socks5_port
        )
        log.info("mhr-ggate proxy listening on %s:%d", self.host, self.socks5_port)
        log.info("Domain fronting: IP=%s  SNI=%s  Host=script.google.com",
                 self.config.get("google_ip"), self.config.get("front_domain"))
        async with server:
            await server.serve_forever()


# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="mhr-ggate local proxy")
    parser.add_argument("-c", "--config", default="config.json")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    try:
        with open(args.config) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Config not found: {args.config}")
        print("Copy config.example.json to config.json and fill in your values.")
        sys.exit(1)

    level = args.log_level or config.get("log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 50)
    print("  mhr-ggate | Domain Fronting Proxy")
    print("=" * 50)
    print(f"  Fronting IP  : {config.get('google_ip')}")
    print(f"  SNI (DPI sees): {config.get('front_domain')}")
    print(f"  Real host    : script.google.com (inside TLS)")
    print(f"  SOCKS5       : {config.get('listen_host')}:{config.get('socks5_port', 1080)}")
    print("=" * 50)

    try:
        asyncio.run(ProxyServer(config).start())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
