#!/usr/bin/env bash
# Reproducible first installation. Thawing uses systemd, never reinstalls models.
set -euo pipefail
BASE=/srv/owl
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Owl references are private: copy knd/server/refs from knd-presentation-sources.
REFS_DIR=${KND_REFS_DIR:-$SCRIPT_DIR/refs}
shopt -s nullglob
REFS=("$REFS_DIR"/*.png)
shopt -u nullglob
if [ ${#REFS[@]} -eq 0 ]; then
  echo "No owl references in $REFS_DIR. Copy knd/server/refs from the private knd-presentation-sources repo or set KND_REFS_DIR." >&2
  exit 1
fi
# Generation jobs (prompts) are private too: knd/server/jobs_*.json in knd-presentation-sources.
JOBS_DIR=${KND_JOBS_DIR:-$SCRIPT_DIR}
for job in jobs_knd_smoke.json jobs_knd_dashboard.json; do
  if [ ! -f "$JOBS_DIR/$job" ]; then
    echo "Missing $JOBS_DIR/$job. Copy knd/server/jobs_*.json from the private knd-presentation-sources repo or set KND_JOBS_DIR." >&2
    exit 1
  fi
done
DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential
if ! id owl >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$BASE" --shell /usr/sbin/nologin owl
fi
mkdir -p "$BASE"/{bin,in,out,logs}
chown owl:owl "$BASE" "$BASE/bin" "$BASE/in" "$BASE/out" "$BASE/logs"
if [ ! -x "$BASE/bin/uv" ]; then
  curl --fail --location --retry 3 --connect-timeout 10 --max-time 120 https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/knd-uv.tar.gz
  tar -xzf /tmp/knd-uv.tar.gz -C "$BASE/bin" --strip-components=1
fi
mkdir -p "$BASE/ComfyUI"
chown owl:owl "$BASE/ComfyUI"
if [ ! -d "$BASE/ComfyUI/.git" ]; then
  runuser -u owl -- git init -q "$BASE/ComfyUI"
fi
if [ ! -f "$BASE/ComfyUI/requirements.txt" ]; then
  if ! runuser -u owl -- git -C "$BASE/ComfyUI" remote get-url origin >/dev/null 2>&1; then
    runuser -u owl -- git -C "$BASE/ComfyUI" remote add origin https://github.com/Comfy-Org/ComfyUI.git
  fi
  runuser -u owl -- git -C "$BASE/ComfyUI" fetch --depth 1 origin HEAD
  runuser -u owl -- git -C "$BASE/ComfyUI" checkout -B knd-runtime FETCH_HEAD
fi
cd "$BASE/ComfyUI"
if [ ! -d .venv ]; then
  runuser -u owl -- "$BASE/bin/uv" venv --python 3.12 .venv
fi
runuser -u owl -- "$BASE/bin/uv" pip install --python .venv/bin/python torch==2.14.1 torchvision==0.29.1 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
runuser -u owl -- "$BASE/bin/uv" pip install --python .venv/bin/python -r requirements.txt huggingface-hub
if [ ! -d custom_nodes/ComfyUI-SeedVR2_VideoUpscaler ]; then
  runuser -u owl -- git clone --depth 1 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git custom_nodes/ComfyUI-SeedVR2_VideoUpscaler
fi
runuser -u owl -- "$BASE/bin/uv" pip install --python .venv/bin/python -r custom_nodes/ComfyUI-SeedVR2_VideoUpscaler/requirements.txt
runuser -u owl -- .venv/bin/python -c 'import torch; print("PyTorch",torch.__version__,"CUDA",torch.cuda.is_available(),torch.cuda.get_device_name(0))'
runuser -u owl -- git rev-parse HEAD > "$BASE/logs/comfy-commit.txt"
runuser -u owl -- "$BASE/bin/uv" pip freeze --python .venv/bin/python > "$BASE/logs/requirements-installed.txt"
cat > /etc/systemd/system/owl-comfy.service <<'UNIT'
[Unit]
Description=KND owl media generation (ComfyUI, SSH access only)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=owl
Group=owl
WorkingDirectory=/srv/owl/ComfyUI
ExecStartPre=/usr/bin/nvidia-smi
ExecStart=/srv/owl/ComfyUI/.venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --input-directory /srv/owl/in --output-directory /srv/owl/out
Restart=on-failure
RestartSec=10
TimeoutStopSec=60
NoNewPrivileges=true
PrivateTmp=true
UMask=0027

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now owl-comfy.service
for script in owl_run.py owl_upscale.py run_when_ready.py; do
  install -o owl -g owl -m 644 "$SCRIPT_DIR/$script" "$BASE/$script"
done
for job in jobs_knd_smoke.json jobs_knd_dashboard.json; do
  install -o owl -g owl -m 644 "$JOBS_DIR/$job" "$BASE/$job"
done
for ref in "${REFS[@]}"; do
  install -o owl -g owl -m 644 "$ref" "$BASE/in/$(basename "$ref")"
done
echo 'Runtime installed. ComfyUI listens only on 127.0.0.1:8188.'
