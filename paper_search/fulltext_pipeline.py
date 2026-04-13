"""Summarize Notion papers from full text fetched via their stored URLs."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from paper_search.fulltext import MIN_FULLTEXT_CHARS, get_full_text
from paper_search.notion_sync import get_notion_client
from paper_search.qwen_precompute import get_cached_summary_bundle
from paper_search.summarizer import summarize_full_text, summarize_full_text_zh_brief_and_limitations
from paper_search.topics import load_topics

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def _text_content(rich: list[dict] | None) -> str:
    if not rich:
        return ""
    parts = []
    for item in rich:
        parts.append(item.get("plain_text") or item.get("text", {}).get("content", ""))
    return "".join(parts)


def _title_content(title_prop: dict | None) -> str:
    if not title_prop:
        return ""
    return _text_content(title_prop.get("title", []))


def _authors_content(prop: dict | None) -> list[str]:
    text = _text_content((prop or {}).get("rich_text", []))
    return [part.strip() for part in text.split(",") if part.strip()]


def _year_from_props(props: dict) -> str:
    published = (props.get("Published", {}) or {}).get("date") or {}
    start = published.get("start") or ""
    return start[:4] if start else ""


def _venue_from_props(props: dict, fallback: str) -> str:
    for key in ("Venue", "Source"):
        select = (props.get(key, {}) or {}).get("select") or {}
        if select.get("name"):
            return select["name"]
    return fallback


def _iter_sources(topic: dict, source: str = "all") -> list[tuple[str, str, str]]:
    out = []
    if source in ("all", "acl"):
        out.append(("ACL", topic["acl_data_source_id"], topic["acl_database_id"]))
    if source in ("all", "arxiv"):
        out.append(("arxiv", topic["arxiv_data_source_id"], topic["arxiv_database_id"]))
    if source in ("all", "scholar") and topic.get("scholar_data_source_id"):
        out.append(("Scholar", topic["scholar_data_source_id"], topic["scholar_database_id"]))
    return out


def summarize_topic_fulltext(topic_slug: str, source: str = "all", limit: int = 10, force_refresh: bool = False, overwrite: bool = False):
    """Yield events while summarizing one topic from full text."""
    from paper_search.obsidian_export import export_paper_note

    topics = load_topics()
    topic = topics.get(topic_slug)
    if not topic:
        raise ValueError(f"Topic '{topic_slug}' not found")

    notion = get_notion_client()
    stats = {
        "topic": topic_slug,
        "success": 0,
        "skipped": 0,
        "errors": 0,
        "rate_limits": 0,
        "fulltext_failures": 0,
        "breakdown": {},
        "model": os.environ.get("OPENROUTER_MODEL", ""),
    }

    for label, ds_id, _db_id in _iter_sources(topic, source=source):
        if stats["success"] >= limit:
            break

        cursor = None
        while stats["success"] < limit:
            kwargs = {"data_source_id": ds_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = notion.data_sources.query(**kwargs)
            pages = response.get("results", [])
            if not pages:
                break

            for page in pages:
                if stats["success"] >= limit:
                    break

                props = page.get("properties", {})
                title = _title_content(props.get("Title", {})).strip()
                authors = _authors_content(props.get("Authors", {}))
                year = _year_from_props(props)
                venue = _venue_from_props(props, label)
                url = (props.get("URL", {}) or {}).get("url") or ""
                summary = _text_content((props.get("Summary", {}) or {}).get("rich_text", [])).strip()
                if summary and not overwrite:
                    stats["skipped"] += 1
                    continue
                if not url:
                    stats["skipped"] += 1
                    yield {"status": "skip", "title": title, "source": label, "reason": "missing_url"}
                    continue

                try:
                    fulltext = get_full_text(url, force_refresh=force_refresh)
                    text = (fulltext.get("text") or "").strip()
                    if len(text) < MIN_FULLTEXT_CHARS:
                        stats["fulltext_failures"] += 1
                        stats["skipped"] += 1
                        yield {
                            "status": "skip",
                            "title": title,
                            "source": label,
                            "reason": f"fulltext_too_short:{len(text)}",
                            "url": url,
                            "cache_path": fulltext.get("cache_path"),
                        }
                        continue

                    cached_bundle = get_cached_summary_bundle(source_url=url, paper_id=page.get("id", "")) or {}
                    generated = str(cached_bundle.get("summary") or "").strip()
                    extras = {
                        "zh_brief": str(cached_bundle.get("zh_brief") or "").strip(),
                        "limitations": cached_bundle.get("paper_limitations") or [],
                    }
                    if not generated:
                        generated = summarize_full_text(title, text)
                    if not extras["zh_brief"] and not extras["limitations"]:
                        extras = summarize_full_text_zh_brief_and_limitations(title, text)

                    notion.pages.update(
                        page_id=page["id"],
                        properties={
                            "Summary": {"rich_text": [{"text": {"content": generated[:2000]}}]},
                        },
                    )
                    obsidian = export_paper_note(
                        title=title,
                        authors=authors,
                        year=year,
                        venue=venue,
                        topic_slug=topic_slug,
                        source_label=label,
                        source_url=url,
                        notion_url=page.get("url", ""),
                        notion_page_id=page.get("id", ""),
                        summary=generated,
                        fulltext_cache_path=fulltext.get("cache_path", ""),
                        document_cache_path=fulltext.get("document_cache_path"),
                        resolved_url=fulltext.get("resolved_url"),
                        zh_brief=extras.get("zh_brief", "待补充。"),
                        limitations=extras.get("limitations") or [],
                    )
                    stats["success"] += 1
                    key = f"{topic_slug}/{label}"
                    stats["breakdown"][key] = stats["breakdown"].get(key, 0) + 1
                    yield {
                        "status": "done",
                        "title": title,
                        "source": label,
                        "url": url,
                        "cache_path": fulltext.get("cache_path"),
                        "document_cache_path": fulltext.get("document_cache_path"),
                        "resolved_url": fulltext.get("resolved_url"),
                        "obsidian_note": obsidian.get("note_path"),
                    }
                except Exception as e:
                    stats["errors"] += 1
                    if "429" in str(e):
                        stats["rate_limits"] += 1
                    yield {
                        "status": "error",
                        "title": title,
                        "source": label,
                        "url": url,
                        "error": str(e),
                    }

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

    yield {"total": True, **stats}


def summarize_all_topics_fulltext(limit: int = 10, source: str = "all", force_refresh: bool = False, overwrite: bool = False):
    """Yield events while summarizing across all topics with a global success limit."""
    topics = list(load_topics().keys())
    remaining = limit
    aggregate = {
        "success": 0,
        "skipped": 0,
        "errors": 0,
        "rate_limits": 0,
        "fulltext_failures": 0,
        "breakdown": {},
        "model": os.environ.get("OPENROUTER_MODEL", ""),
    }

    for slug in topics:
        if remaining <= 0:
            break
        topic_success = 0
        for event in summarize_topic_fulltext(slug, source=source, limit=remaining, force_refresh=force_refresh, overwrite=overwrite):
            if event.get("total"):
                aggregate["success"] += event["success"]
                aggregate["skipped"] += event["skipped"]
                aggregate["errors"] += event["errors"]
                aggregate["rate_limits"] += event["rate_limits"]
                aggregate["fulltext_failures"] += event["fulltext_failures"]
                for k, v in event["breakdown"].items():
                    aggregate["breakdown"][k] = aggregate["breakdown"].get(k, 0) + v
                remaining = limit - aggregate["success"]
                break
            if event.get("status") == "done":
                topic_success += 1
            yield event

    yield {"total": True, **aggregate}
