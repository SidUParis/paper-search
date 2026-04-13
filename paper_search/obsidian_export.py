"""Export summarized papers and local assets into the Obsidian vault."""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian Vault"


def get_obsidian_vault() -> Path:
    raw = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(raw).expanduser() if raw else DEFAULT_VAULT


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def _short_title_slug(title: str, max_words: int = 6) -> str:
    words = [w for w in _slugify(title).split("-") if w]
    stop = {"the", "a", "an", "of", "for", "and", "to", "in", "on", "with", "using"}
    filtered = [w for w in words if w not in stop] or words
    return "-".join(filtered[:max_words])


def _first_author_lastname(authors: list[str]) -> str:
    if not authors:
        return "unknown"
    first = authors[0].strip()
    tokens = [t for t in re.split(r"\s+", first) if t]
    return _slugify(tokens[-1] if tokens else "unknown") or "unknown"


def make_paper_id(title: str, authors: list[str], year: int | str | None) -> str:
    year_str = str(year) if year else "unknown"
    return f"{year_str}-{_first_author_lastname(authors)}-{_short_title_slug(title)}"


def _yaml_list(items: list[str]) -> str:
    safe = [item.replace('"', "'") for item in items if item]
    return "[" + ", ".join(f'"{x}"' for x in safe) + "]"


def _copy_asset(src: str | None, dst: Path) -> str:
    if not src:
        return ""
    source = Path(src)
    if not source.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dst.resolve():
        shutil.copy2(source, dst)
    return str(dst)


def _append_unique_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if line not in existing:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        existing += line + "\n"
        path.write_text(existing, encoding="utf-8")


def export_paper_note(
    *,
    title: str,
    authors: list[str],
    year: int | str | None,
    venue: str,
    topic_slug: str,
    source_label: str,
    source_url: str,
    notion_url: str,
    notion_page_id: str,
    summary: str,
    fulltext_cache_path: str,
    document_cache_path: str | None = None,
    resolved_url: str | None = None,
    zh_brief: str = "待补充。",
    limitations: list[str] | None = None,
) -> dict:
    vault = get_obsidian_vault()
    papers_dir = vault / "papers"
    pdf_dir = papers_dir / "pdfs"
    fulltext_dir = papers_dir / "fulltext"
    notes_dir = papers_dir

    paper_id = make_paper_id(title, authors, year)
    today = datetime.now().strftime("%Y-%m-%d")

    note_path = notes_dir / f"{paper_id}.md"
    fulltext_target = fulltext_dir / f"{paper_id}.md"

    doc_ext = Path(document_cache_path).suffix if document_cache_path else ""
    if not doc_ext:
        doc_ext = ".pdf" if (resolved_url or source_url).lower().endswith('.pdf') else ".html"
    document_target = pdf_dir / f"{paper_id}{doc_ext}"

    copied_fulltext = _copy_asset(fulltext_cache_path, fulltext_target)
    copied_document = _copy_asset(document_cache_path, document_target) if document_cache_path else ""

    tags = ["paper", "summarized", topic_slug, venue.lower() if venue else source_label.lower()]
    aliases = [title]
    year_value = str(year) if year else ""
    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", source_url or resolved_url or "", re.I)
    arxiv_id = arxiv_match.group(1).replace('.pdf', '') if arxiv_match else ""

    limitations = limitations or []
    limitations_md = "\n".join(f"- {x}" for x in limitations) if limitations else "待补充。"

    note = f'''---
title: "{title.replace('"', "'")}"
created: {today}
updated: {today}
type: paper
tags: { _yaml_list(tags) }
sources: []
notion_url: "{notion_url}"
status: active
aliases: { _yaml_list(aliases) }
area: "{topic_slug}"
project: "thesis"
language_scope: [english]
priority: medium
review_status: summarized
paper_id: "{paper_id}"
arxiv_id: "{arxiv_id}"
year: {year_value}
venue: "{venue or source_label}"
authors: { _yaml_list(authors) }
notion_page_id: "{notion_page_id}"
source_url: "{source_url}"
resolved_pdf_url: "{resolved_url or ''}"
local_pdf: "{copied_document}"
local_fulltext: "{copied_fulltext}"
---

# One-sentence takeaway

{summary.splitlines()[0] if summary.strip() else ''}

# 中文简述

{zh_brief}

# Metadata
- Paper ID: {paper_id}
- Notion link: {notion_url}
- Source URL: {source_url}
- Resolved PDF: {resolved_url or ''}
- Local document: {copied_document}
- Local full text: {copied_fulltext}

# Summary

{summary}

# Full text assets
- PDF / HTML cache: `{copied_document}`
- Extracted full text: `{copied_fulltext}`

# Why it matters for my thesis

待补充。

# Limitations / caveats

{limitations_md}

# Connections
- [[concepts/llm-bias]]
- [[projects/frenchbbq]]
- [[projects/multilingual-unified-bbq]]

# Open questions
- 
'''

    note_path.write_text(note, encoding="utf-8")

    index_path = papers_dir / "index.md"
    _append_unique_line(index_path, f'- [[papers/{paper_id}]] — {title}')

    log_path = vault / "log.md"
    _append_unique_line(log_path, f'## [{today}] create | paper note for {title}')
    _append_unique_line(log_path, f'- Added [[papers/{paper_id}]] from full-text pipeline with local cached assets.')

    return {
        "paper_id": paper_id,
        "note_path": str(note_path),
        "document_path": copied_document,
        "fulltext_path": copied_fulltext,
        "vault": str(vault),
    }
