#!/usr/bin/env bash
set -euo pipefail

APP_NAME="investment-portfolio-app"
INSTALL_DIR="/opt/${APP_NAME}"
SERVICE_NAME="${APP_NAME}.service"
APP_USER="${SUDO_USER:-$USER}"
APP_GROUP="$(id -gn "$APP_USER")"
PYTHON_BIN="/usr/bin/python3"
PORT="${PORTFOLIO_PORT:-8080}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Execute com sudo: sudo bash install_raspberry.sh"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 || ! command -v rsync >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 rsync
fi

echo "Instalando em ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"

rsync -a \
  --exclude ".git" \
  --exclude ".agents" \
  --exclude ".codex" \
  --exclude "__pycache__" \
  --exclude "*.log" \
  --exclude "server.err.log" \
  --exclude "server.log" \
  ./ "$INSTALL_DIR"/

mkdir -p "$INSTALL_DIR/data"
chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR"

cat > "/etc/systemd/system/${SERVICE_NAME}" <<SERVICE
[Unit]
Description=Investment Portfolio App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${INSTALL_DIR}
Environment=PORTFOLIO_HOST=0.0.0.0
Environment=PORTFOLIO_PORT=${PORT}
ExecStart=${PYTHON_BIN} -u ${INSTALL_DIR}/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

IP_ADDR="$(hostname -I | awk '{print $1}')"

echo
echo "Instalacao concluida."
echo "Servico: ${SERVICE_NAME}"
echo "Status: systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
echo "Acesse no Raspberry: http://127.0.0.1:${PORT}/"
if [[ -n "${IP_ADDR:-}" ]]; then
  echo "Acesse na rede:      http://${IP_ADDR}:${PORT}/"
fi
