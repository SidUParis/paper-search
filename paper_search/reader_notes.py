"""Save AI reading notes from the private reader back to Notion.

The reader site is a generated view; Notion remains the source of truth. This
module deliberately exposes small, explicit write operations so the UI can show a
preview/confirmation before changing the underlying Notion page.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from paper_search.notion_sync import get_notion_client


PROPERTY_DESTINATIONS: dict[str, str] = {
    "TLDR": "TLDR",
    "Chinese Brief": "Chinese Brief",
    "Method": "Method",
    "Results": "Results",
    "Limitations": "Limitations",
    "PhD Relevance": "PhD Relevance",
    "Relevance": "Relevance",
    "Related Work": "Related Work",
}

APPEND_DESTINATIONS = {"AI Note", "Conversation", "Related Work", "PhD Relevance"}


def _load_papers(site_dir: Path) -> list[dict[str, Any]]:
    data_path = site_dir / "data" / "papers.json"
    if not data_path.exists():
        return []
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("papers"), list):
        return [item for item in data["papers"] if isinstance(item, dict)]
    return []


def _find_paper(site_dir: Path, paper_key: str) -> dict[str, Any]:
    key = str(paper_key or "").strip()
    if not key:
        raise ValueError("missing_paper_key")
    for paper in _load_papers(site_dir):
        if str(paper.get("paper_id") or "") == key:
            return paper
    raise KeyError(f"paper_not_found:{key}")


def _truncate(text: str, limit: int = 1900) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rich_text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": _truncate(content)}}]


def _paragraph(content: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(content)}}


def build_append_note_blocks(*, title: str, question: str, answer: str, destination: str) -> list[dict[str, Any]]:
    """Build a compact append-only Notion block group for one AI note."""

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks: list[dict[str, Any]] = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": _rich_text(f"AI Reading Note — {stamp}")},
        },
        _paragraph(f"Paper: {title}"),
        _paragraph(f"Destination: {destination or 'AI Note'}"),
    ]
    if question:
        blocks.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _rich_text("Question")},
            }
        )
        blocks.append(_paragraph(question))
    blocks.append(
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text("AI Answer")},
        }
    )
    for chunk in _chunk_text(answer):
        blocks.append(_paragraph(chunk))
    return blocks


def _chunk_text(text: str, limit: int = 1800) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return [""]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


def _property_payload(destination: str, answer: str) -> dict[str, Any]:
    property_name = PROPERTY_DESTINATIONS.get(destination)
    if not property_name:
        raise ValueError(f"unsupported_destination:{destination}")
    return {property_name: {"rich_text": _rich_text(answer)}}


def preview_note_update(*, site_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a safe preview of what would be written to Notion."""

    paper = _find_paper(site_dir, str(payload.get("paper_key") or ""))
    destination = str(payload.get("destination") or "AI Note").strip() or "AI Note"
    mode = str(payload.get("mode") or "append").strip() or "append"
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        raise ValueError("missing_answer")
    if mode == "property" and destination not in PROPERTY_DESTINATIONS:
        raise ValueError(f"unsupported_destination:{destination}")
    if mode == "append" and destination not in APPEND_DESTINATIONS and destination not in PROPERTY_DESTINATIONS:
        raise ValueError(f"unsupported_destination:{destination}")
    return {
        "ok": True,
        "paper_id": paper.get("paper_id"),
        "title": paper.get("title"),
        "mode": mode,
        "destination": destination,
        "preview": _truncate(answer, 1200),
    }


def save_note_to_notion(
    *,
    site_dir: Path,
    payload: dict[str, Any],
    notion_client: Any | None = None,
) -> dict[str, Any]:
    """Append an AI note to a Notion page or update an allowed rich-text field."""

    preview = preview_note_update(site_dir=site_dir, payload=payload)
    paper_id = str(preview["paper_id"] or "")
    title = str(preview.get("title") or "Untitled paper")
    mode = str(preview["mode"])
    destination = str(preview["destination"])
    question = str(payload.get("question") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    client = notion_client or get_notion_client()

    if mode == "property":
        properties = _property_payload(destination, answer)
        client.pages.update(page_id=paper_id, properties=properties)
    elif mode == "append":
        blocks = build_append_note_blocks(title=title, question=question, answer=answer, destination=destination)
        client.blocks.children.append(block_id=paper_id, children=blocks)
    else:
        raise ValueError(f"unsupported_mode:{mode}")

    return {
        "ok": True,
        "paper_id": paper_id,
        "title": title,
        "mode": mode,
        "destination": destination,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

READING_STATUS_ALIASES: dict[str, str] = {
    "new": "New",
    "unread": "To Read",
    "to read": "To Read",
    "todo": "To Read",
    "reading": "Reading",
    "in progress": "Reading",
    "read": "Read",
    "done": "Read",
    "finished": "Read",
    "archived": "Archived",
}


def normalize_reading_status(value: str) -> str:
    key = str(value or "").strip().lower().replace("_", "-").replace("-", " ")
    status = READING_STATUS_ALIASES.get(key)
    if not status:
        raise ValueError(f"unsupported_reading_status:{value}")
    return status


def _write_paper_metadata(site_dir: Path, paper_id: str, updates: dict[str, Any]) -> None:
    data_path = site_dir / "data" / "papers.json"
    papers = _load_papers(site_dir)
    changed = False
    for paper in papers:
        if str(paper.get("paper_id") or "") == paper_id:
            paper.update(updates)
            changed = True
            break
    if changed:
        data_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")


def update_reading_status(
    *,
    site_dir: Path,
    payload: dict[str, Any],
    notion_client: Any | None = None,
) -> dict[str, Any]:
    """Set the reading workflow status for a generated paper and Notion page."""

    paper = _find_paper(site_dir, str(payload.get("paper_key") or ""))
    paper_id = str(paper.get("paper_id") or "")
    status = normalize_reading_status(str(payload.get("status") or ""))
    client = notion_client or get_notion_client()
    client.pages.update(page_id=paper_id, properties={"Status": {"select": {"name": status}}})
    _write_paper_metadata(site_dir, paper_id, {"status": status, "reading_status": status})
    return {
        "ok": True,
        "paper_id": paper_id,
        "title": paper.get("title"),
        "status": status,
        "reading_status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

