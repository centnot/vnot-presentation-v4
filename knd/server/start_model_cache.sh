#!/usr/bin/env bash
set -euo pipefail
BASE=/srv/owl
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! id owl >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$BASE" --shell /usr/sbin/nologin owl
fi
mkdir -p "$BASE"/{bin,in,out,logs}
chown owl:owl "$BASE" "$BASE/bin" "$BASE/in" "$BASE/out" "$BASE/logs"
cd "$BASE"
if [ ! -x "$BASE/bin/uv" ]; then
  curl --fail --location --retry 3 --connect-timeout 10 --max-time 120 https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/knd-uv.tar.gz
  tar -xzf /tmp/knd-uv.tar.gz -C "$BASE/bin" --strip-components=1
fi
if [ ! -d "$BASE/.download-venv" ]; then
  runuser -u owl -- "$BASE/bin/uv" venv --python 3.12 "$BASE/.download-venv"
fi
runuser -u owl -- "$BASE/bin/uv" pip install --python "$BASE/.download-venv/bin/python" huggingface-hub
install -o owl -g owl -m 644 "$SCRIPT_DIR/download_models.py" "$BASE/download_models.py"
cat > /etc/systemd/system/owl-model-cache.service <<'UNIT'
[Unit]
Description=Cache exact KND video model files
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/srv/owl/logs/models-cached.json
StartLimitIntervalSec=180
StartLimitBurst=3

[Service]
Type=oneshot
User=owl
Group=owl
WorkingDirectory=/srv/owl
ExecStart=/srv/owl/.download-venv/bin/python -u /srv/owl/download_models.py
StandardOutput=append:/srv/owl/logs/model-download.log
StandardError=append:/srv/owl/logs/model-download.log
Restart=on-failure
RestartSec=10
TimeoutStartSec=1800
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable owl-model-cache.service
systemctl start --no-block owl-model-cache.service
echo 'Model cache download started independently of GPU driver setup.'
