#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-investment-portfolio-app}"
REPO_URL="${REPO_URL:-https://github.com/ricardolira-rl/investment-portfolio-app.git}"
BRANCH="${BRANCH:-main}"
SOURCE_DIR="${SOURCE_DIR:-/opt/${APP_NAME}-source}"
INSTALL_DIR="${INSTALL_DIR:-/opt/${APP_NAME}}"
SERVICE_NAME="${SERVICE_NAME:-${APP_NAME}.service}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-900}"
TIMER_INTERVAL="${TIMER_INTERVAL:-15min}"
APP_USER="${APP_USER:-${SUDO_USER:-$USER}}"
APP_GROUP="${APP_GROUP:-$(id -gn "$APP_USER")}"
INSTALLED_COMMIT_FILE="${INSTALL_DIR}/.installed_commit"

usage() {
  cat <<EOF
Uso:
  sudo ./auto_update_raspberry.sh --once
  sudo ./auto_update_raspberry.sh --watch
  sudo ./auto_update_raspberry.sh --install-timer

Modos:
  --once           Verifica uma vez, atualiza se houver nova versao e sai.
  --watch          Verifica em loop a cada CHECK_INTERVAL_SECONDS segundos.
  --install-timer  Instala um systemd timer para executar --once periodicamente.

Variaveis opcionais:
  REPO_URL=${REPO_URL}
  BRANCH=${BRANCH}
  SOURCE_DIR=${SOURCE_DIR}
  INSTALL_DIR=${INSTALL_DIR}
  SERVICE_NAME=${SERVICE_NAME}
  CHECK_INTERVAL_SECONDS=${CHECK_INTERVAL_SECONDS}
  TIMER_INTERVAL=${TIMER_INTERVAL}
EOF
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Execute com sudo: sudo ./auto_update_raspberry.sh $*"
    exit 1
  fi
}

install_dependencies() {
  local missing=()
  command -v git >/dev/null 2>&1 || missing+=("git")
  command -v rsync >/dev/null 2>&1 || missing+=("rsync")
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || missing+=("python3")

  if [[ "${#missing[@]}" -gt 0 ]]; then
    apt-get update
    apt-get install -y "${missing[@]}"
  fi
}

ensure_source_repo() {
  if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
    echo "Clonando repositorio em ${SOURCE_DIR}..."
    rm -rf "$SOURCE_DIR"
    git clone --branch "$BRANCH" "$REPO_URL" "$SOURCE_DIR"
  fi

  git -C "$SOURCE_DIR" remote set-url origin "$REPO_URL"
  git -C "$SOURCE_DIR" fetch origin "$BRANCH" --quiet
}

remote_commit() {
  git -C "$SOURCE_DIR" rev-parse "origin/${BRANCH}"
}

installed_commit() {
  if [[ -f "$INSTALLED_COMMIT_FILE" ]]; then
    cat "$INSTALLED_COMMIT_FILE"
  else
    echo ""
  fi
}

sync_application() {
  local target_commit="$1"

  echo "Atualizando para ${target_commit}..."
  git -C "$SOURCE_DIR" checkout --quiet "$BRANCH"
  git -C "$SOURCE_DIR" reset --hard --quiet "$target_commit"

  mkdir -p "$INSTALL_DIR"
  rsync -a --delete \
    --exclude ".git" \
    --exclude ".agents" \
    --exclude ".codex" \
    --exclude "__pycache__" \
    --exclude "data" \
    --exclude "*.log" \
    --exclude "server.err.log" \
    --exclude "server.log" \
    "${SOURCE_DIR}/" "${INSTALL_DIR}/"

  mkdir -p "${INSTALL_DIR}/data"
  chown -R "${APP_USER}:${APP_GROUP}" "$INSTALL_DIR"
  echo "$target_commit" > "$INSTALLED_COMMIT_FILE"

  if systemctl list-unit-files --type=service "$SERVICE_NAME" | grep -q "^${SERVICE_NAME}"; then
    systemctl restart "$SERVICE_NAME"
    echo "Servico reiniciado: ${SERVICE_NAME}"
  else
    echo "Servico ${SERVICE_NAME} nao encontrado. Execute install_raspberry.sh se ainda nao instalou o servico."
  fi
}

check_once() {
  install_dependencies
  ensure_source_repo

  local remote
  local current
  remote="$(remote_commit)"
  current="$(installed_commit)"

  if [[ "$remote" == "$current" ]]; then
    echo "Sem atualizacao. Versao atual: ${current}"
    return 0
  fi

  echo "Nova versao encontrada."
  echo "Instalada: ${current:-nenhuma}"
  echo "Remota:    ${remote}"
  sync_application "$remote"
}

install_timer() {
  require_root "$@"
  install_dependencies

  local script_path="${INSTALL_DIR}/auto_update_raspberry.sh"
  mkdir -p "$INSTALL_DIR"
  cp "$0" "$script_path"
  chmod +x "$script_path"

  cat > "/etc/systemd/system/${APP_NAME}-update.service" <<SERVICE
[Unit]
Description=Update ${APP_NAME} from GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=REPO_URL=${REPO_URL}
Environment=BRANCH=${BRANCH}
Environment=SOURCE_DIR=${SOURCE_DIR}
Environment=INSTALL_DIR=${INSTALL_DIR}
Environment=SERVICE_NAME=${SERVICE_NAME}
ExecStart=${script_path} --once
SERVICE

  cat > "/etc/systemd/system/${APP_NAME}-update.timer" <<TIMER
[Unit]
Description=Periodic update check for ${APP_NAME}

[Timer]
OnBootSec=2min
OnUnitActiveSec=${TIMER_INTERVAL}
Persistent=true
Unit=${APP_NAME}-update.service

[Install]
WantedBy=timers.target
TIMER

  systemctl daemon-reload
  systemctl enable --now "${APP_NAME}-update.timer"

  echo "Timer instalado: ${APP_NAME}-update.timer"
  echo "Intervalo: ${TIMER_INTERVAL}"
  echo "Status: sudo systemctl status ${APP_NAME}-update.timer"
  echo "Logs:   journalctl -u ${APP_NAME}-update.service -f"
}

watch_loop() {
  require_root "$@"
  while true; do
    date "+[%Y-%m-%d %H:%M:%S] Verificando atualizacoes..."
    check_once
    sleep "$CHECK_INTERVAL_SECONDS"
  done
}

main() {
  local mode="${1:---once}"

  case "$mode" in
    --once)
      require_root "$@"
      check_once
      ;;
    --watch)
      watch_loop "$@"
      ;;
    --install-timer)
      install_timer "$@"
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
