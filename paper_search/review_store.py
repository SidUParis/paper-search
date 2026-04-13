"""Local storage helpers for review-layer state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from paper_search.review_projects import ReviewProject

ROOT = Path(__file__).resolve().parent.parent


def get_review_root() -> Path:
    raw = os.environ.get("PAPER_SEARCH_REVIEW_CACHE_DIR")
    if raw:
        return Path(raw).expanduser()
    return ROOT / "cache" / "reviews"


def get_review_dir(review_project_id: str) -> Path:
    return get_review_root() / review_project_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def initialize_review(project: ReviewProject) -> tuple[Path, Path]:
    review_dir = get_review_dir(project.review_project_id)
    review_dir.mkdir(parents=True, exist_ok=True)
    state_path = review_dir / "state.json"
    state = {
        "review_project_id": project.review_project_id,
        "review_project_name": project.review_project_name,
        "source_topic_slug": project.source_topic_slug,
        "config_path": project.config_path,
        "stage": "initialized",
        "candidate_count": 0,
        "screened_count": 0,
    }
    _write_json(state_path, state)
    return review_dir, state_path


def update_state(review_project_id: str, **updates: Any) -> Path:
    state_path = get_review_dir(review_project_id) / "state.json"
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(updates)
    _write_json(state_path, state)
    return state_path


def save_candidates(review_project_id: str, candidates: list[dict[str, Any]]) -> Path:
    path = get_review_dir(review_project_id) / "candidates.jsonl"
    _write_jsonl(path, candidates)
    return path


def save_records(review_project_id: str, records: list[dict[str, Any]]) -> Path:
    path = get_review_dir(review_project_id) / "records.jsonl"
    _write_jsonl(path, records)
    return path


def save_extractions(review_project_id: str, rows: list[dict[str, Any]]) -> Path:
    path = get_review_dir(review_project_id) / "extractions.jsonl"
    _write_jsonl(path, rows)
    return path


def save_synthesis(review_project_id: str, markdown_text: str) -> Path:
    path = get_review_dir(review_project_id) / "synthesis.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")
    return path


def save_idea_slate(review_project_id: str, markdown_text: str) -> Path:
    path = get_review_dir(review_project_id) / "idea_slate.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")
    return path


def save_reading_queue(review_project_id: str, rows: list[dict[str, Any]]) -> Path:
    path = get_review_dir(review_project_id) / "reading_queue.jsonl"
    _write_jsonl(path, rows)
    return path


def save_reading_queue_markdown(review_project_id: str, markdown_text: str) -> Path:
    path = get_review_dir(review_project_id) / "reading_queue.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")
    return path


def save_gap_summary(review_project_id: str, markdown_text: str) -> Path:
    path = get_review_dir(review_project_id) / "gap_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")
    return path


def save_topic_signals(review_project_id: str, payload: dict[str, Any]) -> Path:
    path = get_review_dir(review_project_id) / "topic_signals.json"
    _write_json(path, payload)
    return path


def save_digest(review_project_id: str, markdown_text: str, period: str = "weekly") -> Path:
    path = get_review_dir(review_project_id) / f"{period}_digest.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")
    return path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows
