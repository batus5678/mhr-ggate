"""
mhr-ggate | Local MITM Proxy
------------------------------
Sits on localhost, accepts HTTP/HTTPS proxy connections.
For HTTPS: terminates TLS with a fake cert, reads plain HTTP,
           forwards through domain fronting → GAS → VPS → internet.
For HTTP:  forwards directly through domain fronting.

Usage:
    python proxy.py -c ../config.json

First run generates a CA cert — install it in your browser or you'll get SSL errors.
"""

import asyncio
import json
import logging
import ssl
import sys
import argparse
import urllib.parse

from certs import ensure_ca, make_ssl_context, CA_CERT
from fronting import DomainFrontClient

log = logging.getLogger("Proxy")


class MITMProxy:
    def __init__(self, config: dict):
        self.config  = config
        self.host    = config.get("listen_host", "127.0.0.1")
        self.port    = config.get("listen_port", 8085)
        self.fronter = DomainFrontClient(config)

    async def _forward(self, data: bytes, host: str, port: int) -> bytes:
        target_path = f"/{host}/{port}"
        loop = asyncio.get_event_loop()
        status, body = await loop.run_in_executor(
            None, self.fronter.post, data, target_path
        )
        if status == 0:
            log.warning("Relay failed for %s:%d", host, port)
        return body

    async def _relay_https(self, reader, writer, host, port):
        """MITM: terminate TLS, relay decrypted HTTP through domain fronting."""
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        raw_sock = writer.transport.get_extra_info("socket")
        if raw_sock is None:
            writer.close()
            return

        try:
            ssl_ctx = make_ssl_context(host)
            loop = asyncio.get_event_loop()

            tls_reader = asyncio.StreamReader()
            proto = asyncio.StreamReaderProtocol(tls_reader)

            transport, _ = await loop.create_connection(
                lambda: proto,
                sock=raw_sock,
                ssl=ssl_ctx,
                server_side=True,
            )
            tls_writer = asyncio.StreamWriter(transport, proto, tls_reader, loop)
        except Exception as e:
            log.debug("TLS handshake failed %s: %s", host, e)
            try:
                writer.close()
            except Exception:
                pass
            return

        log.info("[MITM] decrypted %s:%d", host, port)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(tls_reader.read(65536), timeout=30)
                except asyncio.TimeoutError:
                    break
                if not data:
                    break
                response = await self._forward(data, host, port)
                if response:
                    tls_writer.write(response)
                    await tls_writer.drain()
        except (ConnectionResetError, BrokenPipeError, ssl.SSLError):
            pass
        finally:
            try:
                tls_writer.close()
            except Exception:
                pass

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            first_line = await asyncio.wait_for(reader.readline(), timeout=15)
            if not first_line:
                writer.close()
                return

            line = first_line.decode(errors="replace").strip()
            parts = line.split()
            if len(parts) < 2:
                writer.close()
                return

            method, target = parts[0].upper(), parts[1]

            # drain remaining headers
            while True:
                hdr = await reader.readline()
                if hdr in (b"\r\n", b"\n", b""):
                    break

            if method == "CONNECT":
                host, _, port_str = target.rpartition(":")
                port = int(port_str) if port_str.isdigit() else 443
                log.info("[HTTPS] %s:%d", host, port)
                await self._relay_https(reader, writer, host, port)
            else:
                parsed = urllib.parse.urlparse(target)
                host = parsed.hostname or target
                port = parsed.port or 80
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                req = f"{method} {path} HTTP/1.1\r\n\r\n".encode()
                log.info("[HTTP] %s %s:%d", method, host, port)
                response = await self._forward(req, host, port)
                if response:
                    writer.write(response)
                    await writer.drain()

        except Exception as e:
            log.debug("Handler error: %s", e)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def start(self):
        server = await asyncio.start_server(self.handle, self.host, self.port)
        log.info("Proxy listening on %s:%d", self.host, self.port)
        async with server:
            await server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", default="../config.json")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    try:
        with open(args.config) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Config not found: {args.config}")
        sys.exit(1)

    level = args.log_level or config.get("log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)-12s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    ensure_ca()

    print("=" * 60)
    print("  mhr-ggate | MITM Proxy")
    print("=" * 60)
    print(f"  Proxy      : {config.get('listen_host')}:{config.get('listen_port', 8085)}")
    print(f"  SNI        : {config.get('front_domain')} (what DPI sees)")
    print(f"  Real host  : script.google.com (inside TLS, hidden)")
    print()
    print(f"  ⚠  Install the CA cert or HTTPS won't work:")
    print(f"     {CA_CERT.resolve()}")
    print(f"     Chrome/Edge : Settings → Privacy → Manage Certs")
    print(f"                   → Trusted Root CAs → Import")
    print(f"     Firefox     : Settings → Privacy → View Certs")
    print(f"                   → Authorities → Import")
    print("=" * 60)

    try:
        asyncio.run(MITMProxy(config).start())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
