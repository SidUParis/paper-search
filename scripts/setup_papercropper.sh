#!/usr/bin/env bash
set -euo pipefail

TOOL_DIR="${READER_PAPERCROPPER_HOME:-$HOME/.cache/dpr-tools/papercropper}"
SRC_DIR="$TOOL_DIR/PaperCropper"
MODEL_DIR="$TOOL_DIR/models"
VENV_DIR="$TOOL_DIR/venv"
MODEL_FILE="doclayout_yolo_docstructbench_imgsz1280_2501.pt"
MODEL_PATH="$MODEL_DIR/$MODEL_FILE"
TORCH_INDEX_URL="${READER_TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"

mkdir -p "$TOOL_DIR" "$MODEL_DIR"

if [ ! -d "$SRC_DIR/.git" ]; then
  rm -rf "$SRC_DIR"
  git clone --depth 1 https://github.com/fake-learn/PaperCropper "$SRC_DIR"
else
  git -C "$SRC_DIR" pull --ff-only || true
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
"$VENV_DIR/bin/python" -m pip install --index-url "$TORCH_INDEX_URL" torch torchvision
"$VENV_DIR/bin/python" -m pip install PyMuPDF Pillow opencv-python-headless huggingface_hub requests dill matplotlib scipy psutil py-cpuinfo thop pandas seaborn 'albumentations>=1.4.11'
"$VENV_DIR/bin/python" -m pip install --no-deps 'doclayout-yolo==0.0.4'

if [ ! -f "$MODEL_PATH" ]; then
  MODEL_DIR="$MODEL_DIR" "$VENV_DIR/bin/python" - <<'PY'
import os
from huggingface_hub import hf_hub_download
filename = "doclayout_yolo_docstructbench_imgsz1280_2501.pt"
print(hf_hub_download(
    repo_id="juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501",
    filename=filename,
    local_dir=os.environ["MODEL_DIR"],
    local_dir_use_symlinks=False,
))
PY
fi

READER_PAPERCROPPER_MODEL="$MODEL_PATH" "$VENV_DIR/bin/python" - <<'PY'
import os
import torch
import torchvision
from doclayout_yolo import YOLOv10
model_path = os.environ["READER_PAPERCROPPER_MODEL"]
print({
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    "model_exists": os.path.exists(model_path),
    "YOLOv10": YOLOv10.__name__,
})
PY

cat <<EOF

PaperCropper / DocLayout-YOLO is ready.
Add these to .reader/.env or your service environment:

READER_PAPERCROPPER_PYTHON=$VENV_DIR/bin/python
READER_PAPERCROPPER_SCRIPT=$SRC_DIR/extract.py
READER_PAPERCROPPER_MODEL=$MODEL_PATH
READER_PAPERCROPPER_DEVICE=cuda

Fallback can be forced with:
READER_PAPERCROPPER_DISABLE=1
EOF
