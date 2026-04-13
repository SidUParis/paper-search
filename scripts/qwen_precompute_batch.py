#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

from paper_search.fulltext import MIN_FULLTEXT_CHARS, get_full_text
from paper_search.fulltext_pipeline import (
    _authors_content,
    _iter_sources,
    _text_content,
    _title_content,
    _venue_from_props,
    _year_from_props,
)
from paper_search.notion_sync import get_notion_client
from paper_search.obsidian_export import export_paper_note, make_paper_id
from paper_search.qwen_precompute import (
    cache_key,
    generate_review_extraction,
    generate_summary_bundle,
    load_precompute,
    save_precompute,
    save_state,
    load_state,
)
from paper_search.review_extraction import _schema_summary
from paper_search.review_projects import load_review_project
from paper_search.topics import load_topics

load_dotenv(ROOT_DIR / ".env")


def iter_topic_pages(topic_slug: str, source: str = "all"):
    topic = load_topics().get(topic_slug)
    if not topic:
        raise ValueError(f"Topic '{topic_slug}' not found")
    notion = get_notion_client()
    for label, ds_id, _db_id in _iter_sources(topic, source=source):
        cursor = None
        while True:
            kwargs = {"data_source_id": ds_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = notion.data_sources.query(**kwargs)
            pages = response.get("results", [])
            for page in pages:
                props = page.get("properties", {})
                title = _title_content(props.get("Title", {})).strip()
                authors = _authors_content(props.get("Authors", {}))
                year = _year_from_props(props)
                venue = _venue_from_props(props, label)
                source_url = (props.get("URL", {}) or {}).get("url") or ""
                abstract = _text_content((props.get("Abstract", {}) or {}).get("rich_text", []))
                summary = _text_content((props.get("Summary", {}) or {}).get("rich_text", []))
                paper_id = make_paper_id(title, authors, year)
                yield {
                    "notion_page_id": page.get("id", ""),
                    "notion_url": page.get("url", ""),
                    "paper_id": paper_id,
                    "topic_slug": topic_slug,
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
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch precompute paper summaries/zh briefs/extractions with Qwen CLI")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--source", default="all")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--write-obsidian", action="store_true")
    ap.add_argument("--project", default="", help="Optional review project yaml path for extraction precompute")
    ap.add_argument("--model", default=None, help="Optional qwen model name passed to CLI")
    args = ap.parse_args()

    state = load_state()
    done_keys = set(state.get("done_keys") or [])
    project = load_review_project(args.project) if args.project else None

    processed = 0
    updated = 0
    skipped = 0
    errors = 0
    results = []

    for record in iter_topic_pages(args.topic, source=args.source):
        if processed >= args.limit:
            break
        if not record["source_url"]:
            skipped += 1
            results.append({"status": "skip", "paper_id": record["paper_id"], "reason": "missing_url"})
            continue
        key = cache_key(source_url=record["source_url"], paper_id=record["paper_id"])
        if key in done_keys and not args.overwrite:
            skipped += 1
            results.append({"status": "skip", "paper_id": record["paper_id"], "reason": "already_done"})
            continue
        cached = load_precompute(source_url=record["source_url"], paper_id=record["paper_id"])
        if cached and not args.overwrite:
            done_keys.add(key)
            skipped += 1
            results.append({"status": "skip", "paper_id": record["paper_id"], "reason": "cache_exists"})
            continue

        fulltext = get_full_text(record["source_url"])
        text = (fulltext.get("text") or "").strip()
        if len(text) < MIN_FULLTEXT_CHARS:
            skipped += 1
            results.append({"status": "skip", "paper_id": record["paper_id"], "reason": f"fulltext_too_short:{len(text)}"})
            continue

        try:
            bundle = generate_summary_bundle(
                paper_id=record["paper_id"],
                title=record["title"],
                year=record["year"],
                venue=record["venue"],
                paper_text=text,
                model=args.model,
            )
            payload = {
                "paper_id": record["paper_id"],
                "title": record["title"],
                "source_url": record["source_url"],
                "summary_bundle": bundle,
                "review_extractions": {},
            }

            if project:
                candidate = {
                    **record,
                    "summary": bundle.get("summary") or record.get("summary") or "",
                    "zh_brief": bundle.get("zh_brief") or "",
                    "paper_limitations": bundle.get("paper_limitations") or [],
                }
                extraction = generate_review_extraction(
                    project_id=project.review_project_id,
                    record=candidate,
                    schema_summary=_schema_summary(project),
                    model=args.model,
                )
                payload["review_extractions"][project.review_project_id] = extraction

            cache_file = save_precompute(payload, source_url=record["source_url"], paper_id=record["paper_id"])

            if args.write_obsidian:
                export_paper_note(
                    title=record["title"],
                    authors=record["authors"],
                    year=record["year"],
                    venue=record["venue"],
                    topic_slug=record["topic_slug"],
                    source_label=record["source_label"],
                    source_url=record["source_url"],
                    notion_url=record["notion_url"],
                    notion_page_id=record["notion_page_id"],
                    summary=bundle.get("summary") or record.get("summary") or "",
                    fulltext_cache_path=fulltext.get("cache_path", ""),
                    document_cache_path=fulltext.get("document_cache_path"),
                    resolved_url=fulltext.get("resolved_url"),
                    zh_brief=bundle.get("zh_brief") or "待补充。",
                    limitations=bundle.get("paper_limitations") or [],
                )

            done_keys.add(key)
            state["done_keys"] = sorted(done_keys)
            save_state(state)
            processed += 1
            updated += 1
            results.append({
                "status": "done",
                "paper_id": record["paper_id"],
                "cache": str(cache_file),
                "has_extraction": bool(project),
            })
        except Exception as exc:
            errors += 1
            state["last_error"] = {
                "paper_id": record["paper_id"],
                "source_url": record["source_url"],
                "error": f"{type(exc).__name__}: {exc}",
            }
            save_state(state)
            results.append({
                "status": "error",
                "paper_id": record["paper_id"],
                "reason": f"{type(exc).__name__}: {exc}",
            })
            continue

    print(json.dumps({
        "status": "ok",
        "topic": args.topic,
        "project": getattr(project, "review_project_id", ""),
        "processed": processed,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "results": results[:20],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
