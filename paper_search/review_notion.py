"""Load review candidates from the existing Notion-backed corpus."""

from __future__ import annotations

from typing import Any

from paper_search.obsidian_export import make_paper_id
from paper_search.qwen_precompute import merge_candidate_with_precompute
from paper_search.topics import get_topic


def get_notion_client():
    from paper_search.notion_sync import get_notion_client as _get_notion_client

    return _get_notion_client()


def _fulltext_helpers():
    from paper_search.fulltext_pipeline import (
        _authors_content,
        _iter_sources,
        _text_content,
        _title_content,
        _venue_from_props,
        _year_from_props,
    )

    return _authors_content, _iter_sources, _text_content, _title_content, _venue_from_props, _year_from_props


def load_review_candidates(project, source: str = "all", limit: int | None = None) -> list[dict[str, Any]]:
    topic = get_topic(project.source_topic_slug)
    if not topic:
        raise ValueError(f"Topic '{project.source_topic_slug}' not found")

    _authors_content, _iter_sources, _text_content, _title_content, _venue_from_props, _year_from_props = _fulltext_helpers()
    notion = get_notion_client()
    candidates: list[dict[str, Any]] = []

    for label, ds_id, _db_id in _iter_sources(topic, source=source):
        cursor = None
        while limit is None or len(candidates) < limit:
            kwargs = {"data_source_id": ds_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = notion.data_sources.query(**kwargs)
            pages = response.get("results", [])
            if not pages:
                break

            for page in pages:
                if limit is not None and len(candidates) >= limit:
                    break
                props = page.get("properties", {})
                title = _title_content(props.get("Title", {})).strip()
                authors = _authors_content(props.get("Authors", {}))
                year = _year_from_props(props)
                venue = _venue_from_props(props, label)
                source_url = (props.get("URL", {}) or {}).get("url") or ""
                abstract = _text_content((props.get("Abstract", {}) or {}).get("rich_text", []))
                summary = _text_content((props.get("Summary", {}) or {}).get("rich_text", []))

                candidates.append(
                    merge_candidate_with_precompute(
                        {
                            "notion_page_id": page.get("id", ""),
                            "paper_id": make_paper_id(title, authors, year),
                            "topic_slug": project.source_topic_slug,
                            "title": title,
                            "authors": authors,
                            "year": year,
                            "venue": venue,
                            "source_label": label,
                            "source_url": source_url,
                            "abstract": abstract,
                            "summary": summary,
                            "zh_brief": "",
                            "paper_limitations": [],
                        }
                    )
                )

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

    return candidates[:limit] if limit is not None else candidates
