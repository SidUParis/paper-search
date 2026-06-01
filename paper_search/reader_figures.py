"""Extract private PDF visual assets for the reader-site gallery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ReaderFigureAsset:
    """A browser-safe gallery asset emitted into the generated reader site."""

    kind: str
    title: str
    page: int
    src: str
    caption: str = ""
    preview: list[list[str]] | None = None
    extractor: str = "pymupdf"
    width: int = 0
    height: int = 0


PAPERCROPPER_MODEL_FILENAME = "doclayout_yolo_docstructbench_imgsz1280_2501.pt"


def _truthy_env(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_first(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _first_existing(paths: list[str]) -> str:
    for value in paths:
        path = str(value or "").strip()
        if path and Path(path).expanduser().exists():
            return str(Path(path).expanduser())
    return ""


def _resolve_papercropper() -> tuple[str, str, str]:
    """Resolve optional PaperCropper/DocLayout-YOLO runtime.

    ``READER_*`` environment variables are preferred for this reader app, while
    the upstream ``PAPERCROPPER_*`` names are also accepted for compatibility
    with daily-paper-reader and its GitHub Actions setup.
    """

    if _truthy_env("READER_PAPERCROPPER_DISABLE") or _truthy_env("PAPERCROPPER_DISABLE"):
        return "", "", ""
    configured_dir = _env_first("READER_PAPERCROPPER_DIR", "PAPERCROPPER_DIR")
    cache_root = str(Path.home() / ".cache" / "dpr-tools" / "papercropper")
    script_path = _first_existing(
        [
            _env_first("READER_PAPERCROPPER_SCRIPT", "PAPERCROPPER_SCRIPT"),
            str(Path(configured_dir) / "extract.py") if configured_dir else "",
            str(Path(cache_root) / "PaperCropper" / "extract.py"),
            str(Path.home() / ".cache" / "dpr-tools" / "PaperCropper" / "extract.py"),
            "/tmp/PaperCropper/extract.py",
        ]
    )
    model_path = _first_existing(
        [
            _env_first("READER_PAPERCROPPER_MODEL", "PAPERCROPPER_MODEL"),
            str(Path(configured_dir) / "models" / PAPERCROPPER_MODEL_FILENAME) if configured_dir else "",
            str(Path(cache_root) / "models" / PAPERCROPPER_MODEL_FILENAME),
            str(Path.home() / ".cache" / "dpr-tools" / "papercropper" / "models" / PAPERCROPPER_MODEL_FILENAME),
        ]
    )
    python_path = _first_existing(
        [
            _env_first("READER_PAPERCROPPER_PYTHON", "PAPERCROPPER_PYTHON"),
            str(Path(cache_root) / "venv" / "bin" / "python"),
            sys.executable,
        ]
    )
    if not script_path or not model_path or not python_path:
        return "", "", ""
    return python_path, script_path, model_path


def _save_webp_from_image(src_path: Path, dst_path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(src_path) as img:
        img.load()
        width, height = img.size
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            export_img = bg
        elif img.mode != "RGB":
            export_img = img.convert("RGB")
        else:
            export_img = img.copy()
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        export_img.save(dst_path, format="WEBP", quality=84, method=6)
        return width, height


def _collect_papercropper_assets(
    *,
    src_dir: Path,
    out_root: Path,
    public_root: str,
    kind: str,
    file_prefix: str,
    max_items: int,
) -> list[ReaderFigureAsset]:
    if not src_dir.is_dir():
        return []
    items: list[ReaderFigureAsset] = []
    seen: set[bytes] = set()
    paths = sorted(path for path in src_dir.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    for src_path in paths:
        if len(items) >= max_items:
            break
        try:
            digest = src_path.read_bytes()[:64] + str(src_path.stat().st_size).encode()
        except Exception:
            continue
        if digest in seen:
            continue
        seen.add(digest)
        filename = f"{file_prefix}-{len(items) + 1:03d}.webp"
        dst_path = out_root / filename
        try:
            width, height = _save_webp_from_image(src_path, dst_path)
        except Exception:
            continue
        items.append(
            ReaderFigureAsset(
                kind=kind,
                title=f"{kind.title()} crop · {len(items) + 1}",
                page=0,
                src=f"{public_root}/{filename}",
                caption="Detected and cropped locally with PaperCropper / DocLayout-YOLO.",
                extractor="doclayout-yolo",
                width=width,
                height=height,
            )
        )
    return items


def _extract_with_papercropper(
    *,
    paper_id: str,
    pdf_path: Path,
    output_assets_dir: Path,
    public_prefix: str,
    max_images: int,
    max_tables: int,
) -> list[dict[str, Any]]:
    python_path, script_path, model_path = _resolve_papercropper()
    if not python_path or not script_path or not model_path:
        return []

    out_root = output_assets_dir / _safe_segment(paper_id)
    public_root = f"{public_prefix.rstrip('/')}/{_safe_segment(paper_id)}"
    timeout = max(int(_env_first("READER_PAPERCROPPER_TIMEOUT_SECONDS", "PAPERCROPPER_TIMEOUT_SECONDS") or "360"), 30)
    cmd = [
        python_path,
        script_path,
        "--pdf",
        str(pdf_path),
        "--model",
        model_path,
        "--formats",
        "png",
        "--targets",
        "figure,table",
        "--conf",
        _env_first("READER_PAPERCROPPER_CONF", "PAPERCROPPER_CONF") or "0.4",
        "--imgsz",
        _env_first("READER_PAPERCROPPER_IMGSZ", "PAPERCROPPER_IMGSZ") or "1024",
        "--dpi",
        _env_first("READER_PAPERCROPPER_DPI", "PAPERCROPPER_DPI") or "200",
        "--png-dpi",
        _env_first("READER_PAPERCROPPER_PNG_DPI", "PAPERCROPPER_PNG_DPI") or "260",
        "--batch-size",
        _env_first("READER_PAPERCROPPER_BATCH_SIZE", "PAPERCROPPER_BATCH_SIZE") or "4",
        "--padding",
        _env_first("READER_PAPERCROPPER_PADDING", "PAPERCROPPER_PADDING") or "2.0",
    ]
    env = os.environ.copy()
    device = _env_first("READER_PAPERCROPPER_DEVICE", "PAPERCROPPER_DEVICE")
    if device:
        env["PAPERCROPPER_DEVICE"] = device
    with tempfile.TemporaryDirectory(prefix="reader_papercropper_") as tmp:
        cmd[cmd.index("--formats"):cmd.index("--formats")] = ["--output", tmp]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False, env=env)
        if proc.returncode != 0:
            return []
        doc_output = Path(tmp) / pdf_path.stem
        figures = _collect_papercropper_assets(
            src_dir=doc_output / "Figures_png",
            out_root=out_root,
            public_root=public_root,
            kind="figure",
            file_prefix="figure",
            max_items=max_images,
        )
        tables = _collect_papercropper_assets(
            src_dir=doc_output / "Tables_png",
            out_root=out_root,
            public_root=public_root,
            kind="table",
            file_prefix="table",
            max_items=max_tables,
        )
    return [asdict(asset) for asset in [*figures, *tables]]


def _safe_segment(value: str, fallback: str = "paper") -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip(".-_")
    return segment[:80] or fallback


def extract_pdf_gallery(
    *,
    paper_id: str,
    pdf_path: str | Path,
    output_assets_dir: str | Path,
    public_prefix: str = "assets/paper-assets",
    max_pages: int = 12,
    max_images: int = 16,
    max_tables: int = 8,
) -> list[dict[str, Any]]:
    """Extract embedded images and simple table previews from a PDF.

    Files are copied under ``output_assets_dir/<paper_id>/`` and returned paths are
    relative browser URLs under ``public_prefix``. The function deliberately never
    returns the source PDF path, so metadata can be serialized safely in the
    private site JSON.
    """

    path = Path(pdf_path).expanduser()
    if not path.exists() or path.suffix.lower() != ".pdf":
        return []

    papercropper_assets = _extract_with_papercropper(
        paper_id=paper_id,
        pdf_path=path,
        output_assets_dir=Path(output_assets_dir),
        public_prefix=public_prefix,
        max_images=max_images,
        max_tables=max_tables,
    )
    if papercropper_assets:
        return papercropper_assets

    try:
        import pymupdf  # type: ignore
    except Exception:
        return []

    out_root = Path(output_assets_dir) / _safe_segment(paper_id)
    public_root = f"{public_prefix.rstrip('/')}/{_safe_segment(paper_id)}"
    out_root.mkdir(parents=True, exist_ok=True)
    assets: list[ReaderFigureAsset] = []
    seen_xrefs: set[int] = set()

    try:
        doc = pymupdf.open(str(path))
    except Exception:
        return []

    try:
        for page_index in range(min(len(doc), max_pages)):
            page = doc[page_index]
            for image_index, image in enumerate(page.get_images(full=True), start=1):
                if len(assets) >= max_images:
                    break
                xref = int(image[0])
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    continue
                data = extracted.get("image")
                if not data:
                    continue
                ext = _safe_segment(str(extracted.get("ext") or "png"), "png").lower()
                if ext not in {"png", "jpg", "jpeg", "webp"}:
                    ext = "png"
                filename = f"page-{page_index + 1:03d}-image-{image_index:02d}.{ext}"
                (out_root / filename).write_bytes(data)
                assets.append(
                    ReaderFigureAsset(
                        kind="image",
                        title=f"Figure candidate · page {page_index + 1}",
                        page=page_index + 1,
                        src=f"{public_root}/{filename}",
                        caption="Extracted embedded PDF image. Caption detection will be refined in the next pass.",
                    )
                )

            if len([asset for asset in assets if asset.kind == "table"]) >= max_tables:
                continue
            find_tables = getattr(page, "find_tables", None)
            if callable(find_tables):
                try:
                    tables = find_tables()
                except Exception:
                    tables = None
                for table_index, table in enumerate(getattr(tables, "tables", []) or [], start=1):
                    if len([asset for asset in assets if asset.kind == "table"]) >= max_tables:
                        break
                    try:
                        rows = table.extract() or []
                    except Exception:
                        continue
                    preview = [[str(cell or "") for cell in row] for row in rows[:8] if row]
                    if not preview:
                        continue
                    filename = f"page-{page_index + 1:03d}-table-{table_index:02d}.csv"
                    with (out_root / filename).open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.writer(handle)
                        writer.writerows([[str(cell or "") for cell in row] for row in rows])
                    assets.append(
                        ReaderFigureAsset(
                            kind="table",
                            title=f"Table candidate · page {page_index + 1}",
                            page=page_index + 1,
                            src=f"{public_root}/{filename}",
                            caption="Extracted table preview from PDF layout.",
                            preview=preview,
                        )
                    )
    finally:
        doc.close()

    return [asdict(asset) for asset in assets]


def _load_site_papers(site_dir: Path) -> list[dict[str, Any]]:
    data_path = site_dir / "data" / "papers.json"
    if not data_path.exists():
        return []
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("papers"), list):
        return [item for item in data["papers"] if isinstance(item, dict)]
    return []


def extract_figures_for_site_paper(*, site_dir: str | Path, paper_key: str) -> dict[str, Any]:
    """Extract figures/tables for one generated-site paper and update papers.json.

    This powers the in-reader "Extract current PDF figures" button. If the PDF is
    not already cached, the paper's source URL is resolved and downloaded through
    the existing fulltext cache, then only browser-safe relative asset URLs are
    written back to the generated site metadata.
    """

    site = Path(site_dir)
    papers = _load_site_papers(site)
    paper = next((p for p in papers if str(p.get("paper_id") or "") == paper_key), None)
    if paper is None:
        raise KeyError(f"paper not found: {paper_key}")

    pdf_source = str(paper.get("local_document") or "").strip()
    source_url = str(paper.get("source_url") or "").strip()
    if not pdf_source and source_url:
        from paper_search.fulltext import download_document, pdf_cache_path, resolve_pdf_url

        cached = pdf_cache_path(source_url)
        if cached.exists():
            pdf_source = str(cached)
        else:
            resolved = resolve_pdf_url(source_url)
            if not resolved:
                raise ValueError("no resolvable PDF URL for this paper")
            path, mode, _fetched = download_document(source_url, resolved_url=resolved)
            if mode != "pdf":
                raise ValueError("downloaded document is not a PDF")
            pdf_source = str(path)
    if not pdf_source:
        raise ValueError("paper has no local or downloadable PDF")

    figures = extract_pdf_gallery(
        paper_id=paper_key,
        pdf_path=pdf_source,
        output_assets_dir=site / "assets" / "paper-assets",
    )
    paper["figures"] = figures
    (site / "data" / "papers.json").write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "paper_id": paper_key, "figures": figures, "count": len(figures)}
