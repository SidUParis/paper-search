"""Extract private PDF visual assets for the reader-site gallery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import re
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
