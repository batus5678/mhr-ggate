#!/usr/bin/env python3
"""
mhr-ggate | VMess Config Generator (FIXED)
Generates a vmess:// config for v2rayN/Hiddify/NekoBox.
Transport: VMess + SplitHTTP → GAS (domain fronted) → VPS → xray
"""

import argparse
import base64
import json
import uuid
from urllib.parse import urlparse

DEFAULT_GAS_URL = "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"
DEFAULT_UUID    = str(uuid.uuid4())
DEFAULT_PATH    = "/mhr"


GOOGLE_IP = "216.239.38.120"
FRONT_DOMAIN = "www.google.com"

def build_client_config(gas_url, vmess_uuid, path, alter_id=0):
    parsed = urlparse(gas_url)
    gas_host = parsed.netloc
    port = 443 if parsed.scheme == "https" else 80
    full_path = parsed.path + "?path=" + path

    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks",
                "port": 1080,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            },
            {
                "tag": "http",
                "port": 8118,
                "listen": "127.0.0.1",
                "protocol": "http"
            }
        ],
        "outbounds": [
            {
                "tag": "mhr-ggate",
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": GOOGLE_IP,
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
                        "serverName": FRONT_DOMAIN,
                        "allowInsecure": False
                    },
                    "splithttpSettings": {
                        "path": full_path,
                        "host": gas_host,
                        "maxUploadSize": 1000000,
                        "maxConcurrentUploads": 10
                    }
                },
                "mux": {
                    "enabled": True,
                    "concurrency": 8,
                    "xudpConcurrency": 16,
                    "xudpProxyUDP443": "allow"
                }
            },
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block",  "protocol": "blackhole"}
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
                {"type": "field", "network": "tcp,udp",    "outboundTag": "mhr-ggate"}
            ]
        }
    }


def build_vmess_link(gas_url, vmess_uuid, path):
    parsed    = urlparse(gas_url)
    gas_host  = parsed.netloc
    port      = 443 if parsed.scheme == "https" else 80
    full_path = parsed.path + "?path=" + path

    payload = {
        "v":    "2",
        "ps":   "mhr-ggate-fixed",
        "add":  GOOGLE_IP,
        "port": str(port),
        "id":   vmess_uuid,
        "aid":  "0",
        "scy":  "auto",
        "net":  "splithttp",
        "type": "none",
        "host": gas_host,
        "path": full_path,
        "tls":  "tls",
        "sni":  FRONT_DOMAIN,
        "alpn": "",
        "fp":   "chrome"
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return f"vmess://{encoded}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gas-url",  default=DEFAULT_GAS_URL)
    parser.add_argument("--uuid",     default=DEFAULT_UUID)
    parser.add_argument("--path",     default=DEFAULT_PATH)
    parser.add_argument("--alter-id", default=0, type=int)
    args = parser.parse_args()

    if "YOUR_SCRIPT_ID" in args.gas_url:
        print("[!] Set your GAS URL with --gas-url or edit DEFAULT_GAS_URL in this file.\n")

    config   = build_client_config(args.gas_url, args.uuid, args.path, args.alter_id)
    vmess    = build_vmess_link(args.gas_url, args.uuid, args.path)
    out_file = "client_config.json"

    with open(out_file, "w") as f:
        json.dump(config, f, indent=2)

    print("=" * 60)
    print("  mhr-ggate | VMess Config Generator (FIXED)")
    print("=" * 60)
    print(f"  UUID       : {args.uuid}")
    print(f"  GAS URL    : {args.gas_url}")
    print(f"  Config     : {out_file}")
    print()
    print("  vmess:// link (paste into v2rayN / NekoBox / Hiddify):")
    print()
    print(f"  {vmess}")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
