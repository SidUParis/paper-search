"""Sync papers to Notion database."""

from __future__ import annotations

import os
import json
from dotenv import load_dotenv
from paper_search.arxiv_source import Paper

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def get_notion_client():
    """Get an authenticated Notion client."""
    try:
        from notion_client import Client
    except ImportError:
        raise ImportError("notion-client package required: pip install notion-client")

    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise ValueError(
            "NOTION_TOKEN not set in .env. "
            "Create an integration at https://www.notion.so/my-integrations "
            "and share your 'Research Papers' database with it."
        )
    return Client(auth=token)


def sync_papers_to_notion(papers: list[Paper]) -> list[dict]:
    """Push papers to the Notion 'Research Papers' database.

    Returns list of created page metadata.
    """
    client = get_notion_client()
    database_id = os.environ.get("NOTION_DATABASE_ID", "681c5e0e039a446f8d3224a8a70fe5f9")

    created = []
    for paper in papers:
        properties = {
            "Title": {"title": [{"text": {"content": paper.title[:2000]}}]},
            "Authors": {"rich_text": [{"text": {"content": ", ".join(paper.authors)[:2000]}}]},
            "Source": {"select": {"name": paper.source}},
            "URL": {"url": paper.url if paper.url else None},
            "Abstract": {"rich_text": [{"text": {"content": paper.abstract[:2000]}}]},
            "Status": {"select": {"name": "New"}},
        }

        if paper.published:
            properties["Published"] = {
                "date": {"start": paper.published.strftime("%Y-%m-%d")}
            }

        if paper.topics:
            properties["Topics"] = {
                "multi_select": [{"name": t[:100]} for t in paper.topics[:10]]
            }

        try:
            page = client.pages.create(
                parent={"database_id": database_id},
                properties=properties,
            )
            created.append({"title": paper.title, "notion_url": page["url"]})
        except Exception as e:
            created.append({"title": paper.title, "error": str(e)})

    return created
