"""Context assembly for AI reading in the private reader workbench."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from urllib.request import Request, urlopen
import unicodedata


@dataclass(frozen=True, slots=True)
class PaperContext:
    paper: dict[str, Any]
    text: str
    sources: list[str]


def _slugify(text: str, fallback: str = "paper") -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or fallback


def _load_papers(site_dir: Path | str) -> list[dict[str, Any]]:
    data_path = Path(site_dir) / "data" / "papers.json"
    if not data_path.exists():
        return []
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("papers"), list):
        return [item for item in data["papers"] if isinstance(item, dict)]
    return []


def load_reader_index(site_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Load generated `papers.json` and index by paper_id and readable slug."""

    index: dict[str, dict[str, Any]] = {}
    for paper in _load_papers(site_dir):
        paper_id = str(paper.get("paper_id") or "").strip()
        title = str(paper.get("title") or "").strip()
        if paper_id:
            index[paper_id] = paper
        if title:
            index[_slugify(title)] = paper
    return index


def make_head_tail_excerpt(text: str, max_chars: int = 24000) -> str:
    """Clip long paper text while preserving both intro and conclusion/results."""

    text = text.strip()
    if len(text) <= max_chars:
        return text
    if max_chars < 80:
        max_chars = 80
    half = max_chars // 2
    head = text[:half].rstrip()
    tail = text[-half:].lstrip()
    return f"{head}\n\n[MIDDLE OMITTED FOR BREVITY]\n\n{tail}"


def _safe_resolve_path(path_text: str, allowed_roots: list[Path] | None) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    roots = [root.expanduser().resolve() for root in (allowed_roots or [])]
    if roots:
        try:
            if not any(resolved.is_relative_to(root) for root in roots):
                return None
        except AttributeError:  # pragma: no cover - Python 3.8 compatibility guard
            if not any(str(resolved).startswith(str(root)) for root in roots):
                return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _safe_read_text(path_text: str, allowed_roots: list[Path] | None) -> str:
    resolved = _safe_resolve_path(path_text, allowed_roots)
    if resolved is None:
        return ""
    try:
        return resolved.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _extract_pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            pages = []
            for page_index in range(len(doc)):
                page = doc.load_page(page_index)
                raw_text = page.get_text("text")
                text = raw_text.strip() if isinstance(raw_text, str) else str(raw_text or "").strip()
                if text:
                    pages.append(f"[PDF page {page_index + 1}]\n{text}")
            return "\n\n".join(pages)
    except Exception:
        return ""


def _pdf_url_from_source(source_url: str) -> str:
    url = str(source_url or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    if url.lower().endswith(".pdf"):
        return url
    if "aclanthology.org/" in url:
        return url.rstrip("/") + ".pdf"
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/").rstrip("/") + ".pdf"
    return ""


def _safe_extract_remote_pdf_text(url: str, cache_key: str, cache_dir: Path) -> str:
    pdf_url = _pdf_url_from_source(url)
    if not pdf_url:
        return ""
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "-", cache_key or "paper").strip("-") or "paper"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{safe_key}.txt"
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    try:
        req = Request(pdf_url, headers={"User-Agent": "xfairllm-reader/1.0"})
        with urlopen(req, timeout=30) as response:  # noqa: S310 - controlled paper PDF fetch
            pdf_bytes = response.read(60 * 1024 * 1024)
    except Exception:
        return ""
    text = _extract_pdf_text_from_bytes(pdf_bytes)
    if text:
        try:
            cache_path.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return text


def _safe_extract_pdf_text(path_text: str, allowed_roots: list[Path] | None) -> str:
    resolved = _safe_resolve_path(path_text, allowed_roots)
    if resolved is None:
        return ""
    try:
        import fitz
    except ImportError:
        return ""
    try:
        with fitz.open(resolved) as doc:
            pages = []
            for page_index in range(len(doc)):
                page = doc.load_page(page_index)
                raw_text = page.get_text("text")
                text = raw_text.strip() if isinstance(raw_text, str) else str(raw_text or "").strip()
                if text:
                    pages.append(f"[PDF page {page_index + 1}]\n{text}")
            return "\n\n".join(pages)
    except Exception:
        return ""


def _append_section(parts: list[str], label: str, value: Any) -> None:
    if isinstance(value, list):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value or "").strip()
    if text:
        parts.append(f"[{label}] {text}")


def _visual_asset_lines(figures: Any, *, max_items: int = 10) -> list[str]:
    """Format extracted PDF figures/tables as LLM-readable context."""

    if not isinstance(figures, list):
        return []
    lines: list[str] = []
    for idx, raw in enumerate(figures[:max_items], start=1):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "visual").strip()
        title = str(raw.get("title") or f"Visual {idx}").strip()
        page = str(raw.get("page") or "?").strip()
        caption = str(raw.get("caption") or "").strip()
        line = f"- {title} ({kind}, page {page})"
        if caption:
            line += f": {caption}"
        preview = raw.get("preview")
        if isinstance(preview, list) and preview:
            preview_lines: list[str] = []
            for row in preview[:4]:
                if isinstance(row, list):
                    cells = [str(cell).strip() for cell in row[:5] if str(cell).strip()]
                    if cells:
                        preview_lines.append(" | ".join(cells))
            if preview_lines:
                line += "\n  Table preview: " + " / ".join(preview_lines)
        lines.append(line)
    return lines


def build_paper_context(
    site_dir: Path | str,
    paper_key: str,
    mode: str = "balanced",
    allowed_roots: list[Path] | None = None,
    max_fulltext_chars: int = 24000,
) -> PaperContext:
    """Build grounded context text for one paper.

    `paper_key` may be a paper_id or the readable slug derived from the title.
    Local fulltext is read only when it resolves under one of `allowed_roots`.
    """

    index = load_reader_index(site_dir)
    paper = index.get(paper_key)
    if paper is None:
        raise KeyError(f"paper not found: {paper_key}")

    parts: list[str] = []
    sources: list[str] = []
    _append_section(parts, "Title", paper.get("title"))
    _append_section(parts, "Authors", paper.get("authors"))
    _append_section(parts, "Year", paper.get("year"))
    _append_section(parts, "Venue", paper.get("venue") or paper.get("source_label"))
    _append_section(parts, "Topic", paper.get("topic_slug"))
    _append_section(parts, "Tags", paper.get("tags"))
    _append_section(parts, "Abstract", paper.get("abstract"))
    _append_section(parts, "Summary", paper.get("summary"))
    _append_section(parts, "Chinese brief", paper.get("zh_brief"))
    _append_section(parts, "TLDR", paper.get("tldr"))
    _append_section(parts, "Motivation", paper.get("motivation"))
    _append_section(parts, "Method", paper.get("method"))
    _append_section(parts, "Results", paper.get("results"))
    _append_section(parts, "Limitations", paper.get("limitations"))
    _append_section(parts, "Relevance", paper.get("relevance"))

    visual_lines = _visual_asset_lines(paper.get("figures"))
    if visual_lines:
        parts.append("[Extracted visuals]\n" + "\n".join(visual_lines))
        sources.append("Extracted visuals")

    if mode in {"balanced", "deep", "full_pdf"}:
        fulltext = _safe_read_text(str(paper.get("local_fulltext") or ""), allowed_roots)
        if not fulltext and mode == "full_pdf":
            fulltext = _safe_extract_pdf_text(str(paper.get("local_document") or ""), allowed_roots)
        if not fulltext and mode == "full_pdf":
            pdf_url = _pdf_url_from_source(str(paper.get("source_url") or ""))
            if pdf_url:
                fulltext = _safe_extract_remote_pdf_text(
                    pdf_url,
                    str(paper.get("paper_id") or paper_key or "paper"),
                    Path(site_dir) / "cache" / "pdf_text",
                )
        if fulltext:
            if mode == "full_pdf":
                fulltext = fulltext.strip()
                if max_fulltext_chars > 0 and len(fulltext) > max_fulltext_chars:
                    parts.append(
                        f"[Full PDF text - clipped at {max_fulltext_chars} chars; original length {len(fulltext)}]\n"
                        f"{make_head_tail_excerpt(fulltext, max_chars=max_fulltext_chars)}"
                    )
                    sources.append("Full PDF text clipped")
                else:
                    parts.append(f"[Full PDF text]\n{fulltext}")
                    sources.append("Full PDF text")
            else:
                excerpt = make_head_tail_excerpt(fulltext, max_chars=max_fulltext_chars)
                parts.append(f"[Fulltext excerpt]\n{excerpt}")
                sources.append("Fulltext excerpt")
        elif mode == "full_pdf":
            parts.append("[Full PDF status] Local fulltext/PDF text is not available for this paper; answer only from synced metadata/notes and say when evidence is insufficient.")

    return PaperContext(paper=paper, text="\n\n".join(parts), sources=sources)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9]{3,}", text.lower()) if token}


def related_papers(site_dir: Path | str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Return simple lexical related-paper matches from generated metadata."""

    query_tokens = _tokens(query)
    scored: list[tuple[int, dict[str, Any]]] = []
    for paper in _load_papers(site_dir):
        haystack = " ".join(
            str(paper.get(key) or "")
            for key in ["title", "abstract", "summary", "zh_brief", "limitations", "relevance", "topic_slug", "source_label"]
        )
        if isinstance(paper.get("tags"), list):
            haystack += " " + " ".join(str(tag) for tag in paper["tags"])
        score = len(query_tokens & _tokens(haystack))
        if score > 0:
            scored.append((score, paper))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("title") or "")))
    return [paper for _, paper in scored[:top_k]]
