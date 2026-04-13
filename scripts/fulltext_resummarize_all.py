from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from paper_search.fulltext import MIN_FULLTEXT_CHARS, get_full_text
from paper_search.fulltext_pipeline import _authors_content, _iter_sources, _text_content, _title_content, _venue_from_props, _year_from_props
from paper_search.notion_sync import get_notion_client
from paper_search.obsidian_export import export_paper_note
from paper_search.summarizer import summarize_full_text
from paper_search.topics import load_topics


DEFAULT_STATE = ROOT / "cache" / "fulltext_resummarize_state.json"


def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "started_at": time.time(),
        "updated_at": time.time(),
        "model": os.environ.get("OPENROUTER_MODEL", ""),
        "done_page_ids": [],
        "done_count": 0,
        "error_count": 0,
        "skip_count": 0,
        "fulltext_failures": 0,
        "rate_limits": 0,
        "breakdown": {},
        "errors": [],
    }


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_pages(notion, source: str = "all") -> Iterable[tuple[str, str, dict]]:
    topics = load_topics()
    for topic_slug, topic in topics.items():
        for label, ds_id, _db_id in _iter_sources(topic, source=source):
            cursor = None
            while True:
                kwargs = {"data_source_id": ds_id, "page_size": 100}
                if cursor:
                    kwargs["start_cursor"] = cursor
                response = notion.data_sources.query(**kwargs)
                for page in response.get("results", []):
                    yield topic_slug, label, page
                if not response.get("has_more"):
                    break
                cursor = response.get("next_cursor")


def process_one(notion, topic_slug: str, label: str, page: dict, force_refresh: bool = False) -> tuple[str, dict]:
    props = page.get("properties", {})
    title = _title_content(props.get("Title", {})).strip()
    authors = _authors_content(props.get("Authors", {}))
    year = _year_from_props(props)
    venue = _venue_from_props(props, label)
    url = (props.get("URL", {}) or {}).get("url") or ""
    if not url:
        return "skip", {"reason": "missing_url", "title": title}

    fulltext = get_full_text(url, force_refresh=force_refresh)
    text = (fulltext.get("text") or "").strip()
    if len(text) < MIN_FULLTEXT_CHARS:
        return "skip", {
            "reason": f"fulltext_too_short:{len(text)}",
            "title": title,
            "url": url,
            "cache_path": fulltext.get("cache_path"),
        }

    generated = summarize_full_text(title, text)
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
    )
    return "done", {
        "title": title,
        "url": url,
        "cache_path": fulltext.get("cache_path"),
        "document_cache_path": fulltext.get("document_cache_path"),
        "obsidian_note": obsidian.get("note_path"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Overwrite all synced paper summaries using full text with resumable state.")
    parser.add_argument("--source", choices=["all", "acl", "arxiv", "scholar"], default="all")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE))
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Optional max successful updates for this run; 0 means no limit")
    args = parser.parse_args()

    notion = get_notion_client()
    state_path = Path(args.state_file).expanduser()
    state = load_state(state_path)
    done_page_ids = set(state.get("done_page_ids", []))
    model = os.environ.get("OPENROUTER_MODEL", "")

    print(f"MODEL\t{model}", flush=True)
    print(f"STATE\t{state_path}", flush=True)
    print(f"RESUME_DONE\t{len(done_page_ids)}", flush=True)

    successes_this_run = 0
    seen = 0
    started = time.time()

    for topic_slug, label, page in iter_pages(notion, source=args.source):
        page_id = page["id"]
        if page_id in done_page_ids:
            continue
        seen += 1
        try:
            status, payload = process_one(notion, topic_slug, label, page, force_refresh=args.force_refresh)
            title = payload.get("title", "")
            if status == "done":
                successes_this_run += 1
                state["done_count"] = state.get("done_count", 0) + 1
                key = f"{topic_slug}/{label}"
                state.setdefault("breakdown", {})[key] = state.get("breakdown", {}).get(key, 0) + 1
                print(f"DONE\t{state['done_count']}\t{key}\t{title}", flush=True)
                print(f"CACHE\t{payload.get('cache_path', '')}", flush=True)
                print(f"NOTE\t{payload.get('obsidian_note', '')}", flush=True)
            else:
                state["skip_count"] = state.get("skip_count", 0) + 1
                if str(payload.get("reason", "")).startswith("fulltext_too_short"):
                    state["fulltext_failures"] = state.get("fulltext_failures", 0) + 1
                print(f"SKIP\t{topic_slug}/{label}\t{title}\t{payload.get('reason','skip')}", flush=True)
            done_page_ids.add(page_id)
            state["done_page_ids"] = sorted(done_page_ids)
            save_state(state_path, state)
            if args.limit and successes_this_run >= args.limit:
                break
        except Exception as e:
            state["error_count"] = state.get("error_count", 0) + 1
            if "429" in str(e):
                state["rate_limits"] = state.get("rate_limits", 0) + 1
            state.setdefault("errors", []).append({
                "page_id": page_id,
                "topic": topic_slug,
                "source": label,
                "error": str(e),
                "timestamp": time.time(),
            })
            save_state(state_path, state)
            print(f"ERROR\t{topic_slug}/{label}\t{page_id}\t{e}", flush=True)

    elapsed = time.time() - started
    print(
        "SUMMARY\t"
        + json.dumps(
            {
                "model": model,
                "done_count": state.get("done_count", 0),
                "successes_this_run": successes_this_run,
                "skip_count": state.get("skip_count", 0),
                "error_count": state.get("error_count", 0),
                "rate_limits": state.get("rate_limits", 0),
                "fulltext_failures": state.get("fulltext_failures", 0),
                "elapsed_seconds": round(elapsed, 1),
                "breakdown": state.get("breakdown", {}),
                "state_file": str(state_path),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
