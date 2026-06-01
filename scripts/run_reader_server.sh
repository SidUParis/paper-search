#!/usr/bin/env bash
set -euo pipefail
cd /home/orange/paper-search-reader-site
export READER_PAPERCROPPER_PYTHON="${READER_PAPERCROPPER_PYTHON:-$HOME/.cache/dpr-tools/papercropper/venv/bin/python}"
export READER_PAPERCROPPER_SCRIPT="${READER_PAPERCROPPER_SCRIPT:-$HOME/.cache/dpr-tools/papercropper/PaperCropper/extract.py}"
export READER_PAPERCROPPER_MODEL="${READER_PAPERCROPPER_MODEL:-$HOME/.cache/dpr-tools/papercropper/models/doclayout_yolo_docstructbench_imgsz1280_2501.pt}"
export READER_PAPERCROPPER_DEVICE="${READER_PAPERCROPPER_DEVICE:-cuda}"
export READER_PAPERCROPPER_TIMEOUT_SECONDS="${READER_PAPERCROPPER_TIMEOUT_SECONDS:-600}"
exec python3 -m paper_search.reader_server \
  --site-dir private-reader-site \
  --profile private \
  --site-title 'Sidney Deep Paper Reader' \
  --state-dir .reader \
  --context-root /home/orange/paper-search-reader-site \
  --context-root /home/orange/paper-search \
  --context-root '/home/orange/Documents/Obsidian Vault' \
  --host 127.0.0.1 \
  --port 8765
