"""Topic configuration management."""

from __future__ import annotations

import json
import os

TOPICS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "topics.json")


def load_topics() -> dict:
    """Load all topic configurations."""
    if not os.path.exists(TOPICS_FILE):
        return {}
    with open(TOPICS_FILE) as f:
        return json.load(f)


def save_topics(topics: dict):
    """Save topic configurations."""
    with open(TOPICS_FILE, "w") as f:
        json.dump(topics, f, indent=2)


def get_topic(slug: str) -> dict | None:
    """Get a single topic config by slug."""
    return load_topics().get(slug)


def list_topics() -> list[tuple[str, dict]]:
    """List all topics as (slug, config) pairs."""
    return list(load_topics().items())


def add_topic(
    slug: str,
    name: str,
    keywords: list[str],
    arxiv_queries: list[str],
    acl_database_id: str,
    acl_data_source_id: str,
    arxiv_database_id: str,
    arxiv_data_source_id: str,
    acl_venues: list[str] | None = None,
    acl_years: list[int] | None = None,
) -> dict:
    """Add a new topic to the config."""
    from datetime import datetime

    topics = load_topics()
    topic = {
        "name": name,
        "keywords": keywords,
        "acl_database_id": acl_database_id,
        "acl_data_source_id": acl_data_source_id,
        "arxiv_database_id": arxiv_database_id,
        "arxiv_data_source_id": arxiv_data_source_id,
        "arxiv_queries": arxiv_queries,
        "acl_venues": acl_venues or ["acl", "eacl", "naacl", "emnlp", "findings", "coling"],
        "acl_years": acl_years or [datetime.now().year - 1, datetime.now().year],
        "created": datetime.now().strftime("%Y-%m-%d"),
    }
    topics[slug] = topic
    save_topics(topics)
    return topic
