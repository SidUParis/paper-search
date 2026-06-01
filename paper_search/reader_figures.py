"""Extract private PDF visual assets for the reader-site gallery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
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
