#!/usr/bin/env python3
"""
mhr-gvps | V2ray / Xray Config Generator
Generates a working client config that tunnels through GAS → VPS.
Transport: VMess + SplitHTTP (works over plain HTTP/1.1, no WebSocket upgrade needed)

Usage:
  python3 generate_config.py
  python3 generate_config.py --uuid YOUR_UUID --gas-url https://script.google.com/macros/s/XXXX/exec
"""

import argparse
import json
import uuid
import base64
import sys

# ─── DEFAULT VALUES (edit or pass as flags) ────────────────
DEFAULT_GAS_URL  = "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"
DEFAULT_UUID     = str(uuid.uuid4())
DEFAULT_PATH     = "/mhr"           # SplitHTTP path on your v2ray server
DEFAULT_ALTID    = 0                # VMess alterId (0 = AEAD mode, recommended)
# ──────────────────────────────────────────────────────────


def parse_gas_host(gas_url: str):
    """Extract host from GAS URL."""
    # script.google.com
    from urllib.parse import urlparse
    parsed = urlparse(gas_url)
    return parsed.scheme, parsed.netloc, parsed.path


def build_client_config(gas_url: str, vmess_uuid: str, path: str, alter_id: int) -> dict:
    scheme, host, gas_path = parse_gas_host(gas_url)
    port = 443 if scheme == "https" else 80

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "port": 1080,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            },
            {
                "tag": "http-in",
                "port": 8118,
                "listen": "127.0.0.1",
                "protocol": "http"
            }
        ],
        "outbounds": [
            {
                "tag": "mhr-gvps",
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": host,          # script.google.com
                        "port": port,
                        "users": [{
                            "id": vmess_uuid,
                            "alterId": alter_id,
                            "security": "auto"
                        }]
                    }]
                },
                "streamSettings": {
                    "network": "splithttp",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": host,
                        "allowInsecure": False
                    },
                    "splithttpSettings": {
                        # GAS exec URL path — GAS will relay to your VPS
                        "path": gas_path + "?path=" + path,
                        "host": host,
                        "maxUploadSize": 1000000,
                        "maxConcurrentUploads": 10
                    }
                },
                "mux": {
                    "enabled": True,
                    "concurrency": 8,
                    "xudpConcurrency": 16,    # UDP mux for gaming
                    "xudpProxyUDP443": "allow"
                }
            },
            {
                "tag": "direct",
                "protocol": "freedom",
                "settings": {}
            },
            {
                "tag": "block",
                "protocol": "blackhole"
            }
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                # bypass local traffic
                {
                    "type": "field",
                    "ip": ["geoip:private"],
                    "outboundTag": "direct"
                },
                # everything else → mhr-gvps tunnel
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "outboundTag": "mhr-gvps"
                }
            ]
        }
    }
    return config


def build_vmess_link(gas_url: str, vmess_uuid: str, path: str) -> str:
    """Generate a vmess:// share link."""
    scheme, host, gas_path = parse_gas_host(gas_url)
    port = 443 if scheme == "https" else 80

    payload = {
        "v": "2",
        "ps": "mhr-gvps",
        "add": host,
        "port": str(port),
        "id": vmess_uuid,
        "aid": "0",
        "scy": "auto",
        "net": "splithttp",
        "type": "none",
        "host": host,
        "path": gas_path + "?path=" + path,
        "tls": "tls",
        "sni": host,
        "alpn": "",
        "fp": "chrome"
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"vmess://{encoded}"


def main():
    parser = argparse.ArgumentParser(description="mhr-gvps config generator")
    parser.add_argument("--gas-url",  default=DEFAULT_GAS_URL,  help="GAS Web App URL")
    parser.add_argument("--uuid",     default=DEFAULT_UUID,      help="VMess UUID (generate one with: python3 -c \"import uuid; print(uuid.uuid4())\")")
    parser.add_argument("--path",     default=DEFAULT_PATH,      help="SplitHTTP path on your v2ray server")
    parser.add_argument("--alter-id", default=DEFAULT_ALTID, type=int)
    args = parser.parse_args()

    if "YOUR_SCRIPT_ID" in args.gas_url:
        print("[!] Set your GAS URL with --gas-url or edit DEFAULT_GAS_URL in this file.")
        print()

    config = build_client_config(args.gas_url, args.uuid, args.path, args.alter_id)
    link   = build_vmess_link(args.gas_url, args.uuid, args.path)

    out_file = "client_config.json"
    with open(out_file, "w") as f:
        json.dump(config, f, indent=2)

    print("=" * 60)
    print("  mhr-gvps | Config Generated")
    print("=" * 60)
    print(f"\n[+] UUID     : {args.uuid}")
    print(f"[+] GAS URL  : {args.gas_url}")
    print(f"[+] Path     : {args.path}")
    print(f"[+] Config   : {out_file}  (use with xray/v2ray)")
    print(f"\n[+] vmess:// link (paste into v2rayN / NekoBox / Hiddify):\n")
    print(f"    {link}")
    print()
    print("[+] Local SOCKS5 proxy will be on  127.0.0.1:1080")
    print("[+] Local HTTP  proxy will be on   127.0.0.1:8118")
    print("[+] UDP (gaming) mux is enabled via xudp")
    print("=" * 60)


if __name__ == "__main__":
    main()
