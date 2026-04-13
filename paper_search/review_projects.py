"""Review project configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from paper_search.topics import load_topics


@dataclass
class ReviewProject:
    review_project_id: str
    review_project_name: str
    source_topic_slug: str
    objective: str
    research_questions: list[str]
    inclusion_criteria: list[str]
    exclusion_criteria: list[str]
    screening: dict[str, Any]
    schema: dict[str, Any]
    topic_schema: list[dict[str, Any]]
    raw: dict[str, Any]
    config_path: str


def load_review_project(path: str | Path) -> ReviewProject:
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    review_project_id = data["review_project_id"]
    source_topic_slug = data["source_topic_slug"]
    topics = load_topics()
    if source_topic_slug not in topics:
        raise ValueError(f"Unknown source_topic_slug: {source_topic_slug}")

    schema = data.get("schema") or {}
    topic_schema = schema.get("topic_schema") or []

    return ReviewProject(
        review_project_id=review_project_id,
        review_project_name=data.get("review_project_name") or review_project_id,
        source_topic_slug=source_topic_slug,
        objective=data.get("objective", "").strip(),
        research_questions=list(data.get("research_questions") or []),
        inclusion_criteria=list(data.get("inclusion_criteria") or []),
        exclusion_criteria=list(data.get("exclusion_criteria") or []),
        screening=dict(data.get("screening") or {}),
        schema=schema,
        topic_schema=topic_schema,
        raw=data,
        config_path=str(config_path),
    )
