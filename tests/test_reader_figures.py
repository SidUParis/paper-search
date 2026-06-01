from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image

from paper_search.reader_figures import extract_pdf_gallery


def _write_fake_papercropper(script: Path) -> None:
    script.write_text(
        """
from __future__ import annotations
import argparse
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--pdf', required=True)
parser.add_argument('--model', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--formats')
parser.add_argument('--targets')
parser.add_argument('--conf')
parser.add_argument('--imgsz')
parser.add_argument('--dpi')
parser.add_argument('--png-dpi')
parser.add_argument('--batch-size')
parser.add_argument('--padding')
args = parser.parse_args()
stem = Path(args.pdf).stem
root = Path(args.output) / stem
fig_dir = root / 'Figures_png'
table_dir = root / 'Tables_png'
fig_dir.mkdir(parents=True, exist_ok=True)
table_dir.mkdir(parents=True, exist_ok=True)
Image.new('RGB', (640, 360), (255, 255, 255)).save(fig_dir / 'figure-1.png')
Image.new('RGB', (500, 240), (240, 240, 240)).save(table_dir / 'table-1.png')
""".strip(),
        encoding="utf-8",
    )


def test_extract_pdf_gallery_prefers_papercropper_doclayout_yolo_and_keeps_browser_safe_paths(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake for papercropper test")
    script = tmp_path / "extract.py"
    model = tmp_path / "doclayout_yolo_docstructbench_imgsz1280_2501.pt"
    _write_fake_papercropper(script)
    model.write_bytes(b"fake weights")

    monkeypatch.setenv("READER_PAPERCROPPER_SCRIPT", str(script))
    monkeypatch.setenv("READER_PAPERCROPPER_MODEL", str(model))
    monkeypatch.setenv("READER_PAPERCROPPER_PYTHON", sys.executable)
    monkeypatch.setenv("READER_PAPERCROPPER_DEVICE", "cuda")

    assets = extract_pdf_gallery(paper_id="paper/one", pdf_path=pdf, output_assets_dir=tmp_path / "assets")

    assert [asset["kind"] for asset in assets] == ["figure", "table"]
    assert all(asset["extractor"] == "doclayout-yolo" for asset in assets)
    assert all(asset["src"].startswith("assets/paper-assets/paper-one/") for asset in assets)
    assert str(tmp_path) not in json.dumps(assets)
    assert (tmp_path / "assets" / "paper-one" / "figure-001.webp").exists()
    assert (tmp_path / "assets" / "paper-one" / "table-001.webp").exists()


def test_extract_pdf_gallery_can_disable_papercropper_fallback(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "not-a-real.pdf"
    pdf.write_bytes(b"not a real pdf")
    script = tmp_path / "extract.py"
    model = tmp_path / "model.pt"
    _write_fake_papercropper(script)
    model.write_bytes(b"fake weights")

    monkeypatch.setenv("READER_PAPERCROPPER_SCRIPT", str(script))
    monkeypatch.setenv("READER_PAPERCROPPER_MODEL", str(model))
    monkeypatch.setenv("READER_PAPERCROPPER_PYTHON", sys.executable)
    monkeypatch.setenv("READER_PAPERCROPPER_DISABLE", "1")

    assets = extract_pdf_gallery(paper_id="p1", pdf_path=pdf, output_assets_dir=tmp_path / "assets")

    assert assets == []
