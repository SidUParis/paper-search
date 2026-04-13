"""Fetch, cache, and extract full text for papers from URLs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

ROOT_DIR = Path(os.path.dirname(os.path.dirname(__file__)))
CACHE_DIR = ROOT_DIR / "cache"
PDF_CACHE_DIR = CACHE_DIR / "pdfs"
FULLTEXT_CACHE_DIR = CACHE_DIR / "fulltext"
META_CACHE_DIR = CACHE_DIR / "meta"

USER_AGENT = "paper-search/0.1 (+https://github.com/SidUParis/paper-search)"
MIN_FULLTEXT_CHARS = 3000


def _ensure_cache_dirs() -> None:
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FULLTEXT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    META_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def paper_cache_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:24]


def pdf_cache_path(url: str) -> Path:
    _ensure_cache_dirs()
    return PDF_CACHE_DIR / f"{paper_cache_key(url)}.pdf"


def html_cache_path(url: str) -> Path:
    _ensure_cache_dirs()
    return PDF_CACHE_DIR / f"{paper_cache_key(url)}.html"


def text_cache_path(url: str) -> Path:
    _ensure_cache_dirs()
    return FULLTEXT_CACHE_DIR / f"{paper_cache_key(url)}.md"


def meta_cache_path(url: str) -> Path:
    _ensure_cache_dirs()
    return META_CACHE_DIR / f"{paper_cache_key(url)}.json"


def resolve_pdf_url(url: str) -> str | None:
    """Resolve a paper URL to a likely PDF URL when possible."""
    clean = url.strip()
    if not clean:
        return None

    lower = clean.lower()
    if lower.endswith(".pdf"):
        return clean

    parsed = urlparse(clean)
    host = parsed.netloc.lower()
    path = parsed.path

    if "arxiv.org" in host:
        if "/pdf/" in path:
            return clean if lower.endswith(".pdf") else f"{clean}.pdf"
        if "/abs/" in path:
            paper_id = path.split("/abs/", 1)[1].strip("/")
            return f"https://arxiv.org/pdf/{paper_id}.pdf"

    if "aclanthology.org" in host:
        paper_id = path.strip("/")
        if paper_id:
            return f"https://aclanthology.org/{paper_id}.pdf"

    return None


def _write_meta(url: str, payload: dict) -> None:
    meta_path = meta_cache_path(url)
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def download_document(url: str, resolved_url: str | None = None, timeout: int = 60) -> tuple[Path, str, str]:
    """Download a paper document to cache.

    Returns: (path, mode, fetched_url)
    mode is 'pdf' or 'html'.
    """
    _ensure_cache_dirs()

    fetch_url = resolved_url or url
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(fetch_url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()

    content_type = (response.headers.get("content-type") or "").lower()
    final_url = response.url
    is_pdf = "pdf" in content_type or final_url.lower().endswith(".pdf")

    if is_pdf:
        path = pdf_cache_path(url)
        path.write_bytes(response.content)
        mode = "pdf"
    else:
        path = html_cache_path(url)
        path.write_text(response.text, encoding="utf-8", errors="ignore")
        mode = "html"

    _write_meta(
        url,
        {
            "source_url": url,
            "resolved_url": resolved_url,
            "fetched_url": final_url,
            "mode": mode,
            "cached_at": datetime.utcnow().isoformat() + "Z",
            "cache_path": str(path),
            "content_type": content_type,
        },
    )
    return path, mode, final_url


def extract_full_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pymupdf4llm  # type: ignore

            markdown = pymupdf4llm.to_markdown(str(path))
            if markdown and len(markdown.strip()) >= 500:
                return markdown
        except Exception:
            pass

        import pymupdf  # type: ignore

        doc = pymupdf.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text("text"))
        return "\n\n".join(pages)

    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def get_full_text(url: str, timeout: int = 60, force_refresh: bool = False) -> dict:
    """Fetch and extract full text for a paper URL, using local cache when possible."""
    _ensure_cache_dirs()
    txt_path = text_cache_path(url)
    meta_path = meta_cache_path(url)

    if txt_path.exists() and not force_refresh:
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return {
            "mode": meta.get("mode", "cached"),
            "text": txt_path.read_text(encoding="utf-8", errors="ignore"),
            "source_url": url,
            "resolved_url": meta.get("resolved_url"),
            "fetched_url": meta.get("fetched_url"),
            "cache_path": str(txt_path),
            "document_cache_path": meta.get("cache_path"),
            "meta_path": str(meta_path) if meta_path.exists() else None,
            "cached": True,
        }

    resolved = resolve_pdf_url(url)
    path, mode, fetched_url = download_document(url, resolved_url=resolved, timeout=timeout)
    text = extract_full_text(path).strip()
    txt_path.write_text(text, encoding="utf-8")

    existing_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    existing_meta.update(
        {
            "text_cache_path": str(txt_path),
            "text_length": len(text),
            "resolved_url": resolved,
            "fetched_url": fetched_url,
            "mode": mode,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
    )
    _write_meta(url, existing_meta)

    return {
        "mode": mode,
        "text": text,
        "source_url": url,
        "resolved_url": resolved,
        "fetched_url": fetched_url,
        "cache_path": str(txt_path),
        "document_cache_path": str(path),
        "meta_path": str(meta_path),
        "cached": False,
    }
