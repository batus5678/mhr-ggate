#!/usr/bin/env bash
# mhr-ggate | VPS Install Script
# =================================
# Installs xray-core, Python deps, server.py, nginx, and systemd units
# on a fresh Ubuntu 22.04 / 24.04 VPS.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
#   OR: bash install.sh
#
# Environment vars you can set before running:
#   MHR_SECRET   — the shared secret (required)
#   MHR_DOMAIN   — your domain (or leave empty to skip nginx/TLS setup)
#   XRAY_PORT    — default 10000
#   XRAY_PATH    — default /mhr
#   SERVER_PORT  — default 8080

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✘]${NC} $*" >&2; exit 1; }

# ── Config ────────────────────────────────────────────────────────────────────
MHR_SECRET="${MHR_SECRET:-}"
MHR_DOMAIN="${MHR_DOMAIN:-}"
XRAY_PORT="${XRAY_PORT:-10000}"
XRAY_PATH="${XRAY_PATH:-/mhr}"
SERVER_PORT="${SERVER_PORT:-8080}"
INSTALL_DIR="/opt/mhr-ggate"

echo "============================================================"
echo "  mhr-ggate VPS Installer"
echo "============================================================"
echo

if [[ -z "$MHR_SECRET" ]]; then
    warn "MHR_SECRET not set — generating a random one."
    MHR_SECRET=$(openssl rand -hex 24)
    warn "  Generated secret: ${MHR_SECRET}"
    warn "  Copy this into config.json (auth_key) and Code.gs (SECRET)!"
fi

# ── System deps ───────────────────────────────────────────────────────────────
info "Updating apt and installing dependencies..."
apt-get update -qq
apt-get install -y -qq curl python3 python3-pip nginx certbot python3-certbot-nginx \
    openssl unzip wget

# ── xray-core ─────────────────────────────────────────────────────────────────
info "Installing xray-core..."
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

# Generate a UUID for VMess
UUID=$(xray uuid)
info "Generated UUID: ${UUID}"
warn "  Copy this UUID into server/xray_server.json and client/xray_client.json!"

# ── Python packages ───────────────────────────────────────────────────────────
info "Installing Python packages..."
pip3 install --quiet fastapi uvicorn httpx --break-system-packages

# ── Project directory ─────────────────────────────────────────────────────────
info "Setting up project directory at ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}/server"

# Copy server files (if run from project root)
if [[ -f "server/server.py" ]]; then
    cp -r server "${INSTALL_DIR}/"
    info "Copied server files."
else
    warn "server/ directory not found — copy server.py and xray_server.json to ${INSTALL_DIR}/server/ manually."
fi

# ── xray config ───────────────────────────────────────────────────────────────
info "Writing xray server config..."
cat > "${INSTALL_DIR}/server/xray_server.json" <<XRAYCFG
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "xhttp-in",
      "port": ${XRAY_PORT},
      "listen": "127.0.0.1",
      "protocol": "vmess",
      "settings": {
        "clients": [
          {
            "id": "${UUID}",
            "alterId": 0
          }
        ]
      },
      "streamSettings": {
        "network": "xhttp",
        "xhttpSettings": {
          "path": "${XRAY_PATH}",
          "mode": "packet-up"
        }
      }
    }
  ],
  "outbounds": [
    { "tag": "freedom",   "protocol": "freedom" },
    { "tag": "blackhole", "protocol": "blackhole" }
  ]
}
XRAYCFG

# ── Environment file ─────────────────────────────────────────────────────────
info "Writing environment file..."
cat > /etc/mhr-ggate.env <<ENV
MHR_SECRET=${MHR_SECRET}
XRAY_PORT=${XRAY_PORT}
XRAY_PATH=${XRAY_PATH}
PORT=${SERVER_PORT}
ENV
chmod 600 /etc/mhr-ggate.env

# ── systemd — xray ────────────────────────────────────────────────────────────
info "Creating systemd unit: mhr-xray..."
cat > /etc/systemd/system/mhr-xray.service <<UNIT
[Unit]
Description=mhr-ggate xray tunnel
After=network.target

[Service]
Type=simple
User=nobody
ExecStart=/usr/local/bin/xray run -config ${INSTALL_DIR}/server/xray_server.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# ── systemd — server.py ───────────────────────────────────────────────────────
info "Creating systemd unit: mhr-server..."
cat > /etc/systemd/system/mhr-server.service <<UNIT
[Unit]
Description=mhr-ggate relay server
After=network.target mhr-xray.service

[Service]
Type=simple
User=nobody
WorkingDirectory=${INSTALL_DIR}/server
EnvironmentFile=/etc/mhr-ggate.env
ExecStart=$(which python3) ${INSTALL_DIR}/server/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable mhr-xray mhr-server
systemctl start mhr-xray mhr-server
info "Services started."

# ── nginx ─────────────────────────────────────────────────────────────────────
if [[ -n "$MHR_DOMAIN" ]]; then
    info "Configuring nginx for domain: ${MHR_DOMAIN}..."
    cat > /etc/nginx/sites-available/mhr-ggate <<NGINX
server {
    listen 80;
    server_name ${MHR_DOMAIN};
    location / {
        proxy_pass         http://127.0.0.1:${SERVER_PORT};
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 60s;
    }
}
NGINX
    ln -sf /etc/nginx/sites-available/mhr-ggate /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx
    info "Running certbot for TLS..."
    certbot --nginx -d "${MHR_DOMAIN}" --non-interactive --agree-tos -m "admin@${MHR_DOMAIN}" || \
        warn "certbot failed — set up TLS manually."
else
    warn "MHR_DOMAIN not set — skipping nginx/TLS setup."
    warn "Run:  MHR_DOMAIN=yourdomain.com bash install.sh   to configure TLS."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
echo "============================================================"
echo "  Installation complete!"
echo "============================================================"
echo "  UUID       : ${UUID}"
echo "  Secret     : ${MHR_SECRET}"
echo "  xray port  : ${XRAY_PORT} (localhost only)"
echo "  Server port: ${SERVER_PORT}"
[[ -n "$MHR_DOMAIN" ]] && echo "  Domain     : https://${MHR_DOMAIN}"
echo
echo "  Test server health:"
echo "    curl http://localhost:${SERVER_PORT}/health"
echo
echo "  Service status:"
echo "    systemctl status mhr-xray mhr-server"
echo
echo "  Logs:"
echo "    journalctl -u mhr-xray -f"
echo "    journalctl -u mhr-server -f"
echo "============================================================"
