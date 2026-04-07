"""Sync papers to Notion databases with deduplication."""

from __future__ import annotations

import os
import re
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
            "and share your databases with it."
        )
    return Client(auth=token)


# data_source_id for each database (used by notion-client v3 data_sources.query)
DATA_SOURCES = {
    "681c5e0e039a446f8d3224a8a70fe5f9": "3d43ef78-5f47-4ae1-9f31-fe5b382b680f",  # ACL Research Papers
    "e9b153737d79435e8aa23721899e0ba0": "31ff8b2a-3ee1-430a-9edc-dac225acadcf",  # arxiv Papers
}


def _get_existing_urls(client, database_id: str) -> set[str]:
    """Fetch all existing paper URLs from a Notion database to avoid duplicates."""
    data_source_id = DATA_SOURCES.get(database_id, database_id)
    urls = set()
    start_cursor = None

    while True:
        kwargs = {"data_source_id": data_source_id, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor

        response = client.data_sources.query(**kwargs)

        for page in response["results"]:
            url_prop = page["properties"].get("URL", {})
            if url_prop.get("url"):
                urls.add(url_prop["url"])

        if not response.get("has_more"):
            break
        start_cursor = response.get("next_cursor")

    return urls


def _extract_arxiv_id(url: str) -> str:
    """Extract arxiv ID from URL like http://arxiv.org/abs/2309.02144v1."""
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url)
    return match.group(1) if match else ""


def sync_papers_to_notion(papers: list[Paper], database_id: str | None = None) -> list[dict]:
    """Push papers to the Notion ACL 'Research Papers' database.

    Skips papers whose URL already exists in the database.
    Returns list of created/skipped page metadata.
    """
    client = get_notion_client()
    db_id = database_id or os.environ.get("NOTION_DATABASE_ID", "681c5e0e039a446f8d3224a8a70fe5f9")

    existing_urls = _get_existing_urls(client, db_id)
    results = []

    for paper in papers:
        if paper.url in existing_urls:
            results.append({"title": paper.title, "skipped": "already exists"})
            continue

        properties = {
            "Title": {"title": [{"text": {"content": paper.title[:2000]}}]},
            "Authors": {"rich_text": [{"text": {"content": ", ".join(paper.authors)[:2000]}}]},
            "URL": {"url": paper.url if paper.url else None},
            "Abstract": {"rich_text": [{"text": {"content": paper.abstract[:2000]}}]},
            "Status": {"select": {"name": "New"}},
        }

        # ACL database has Source field
        if paper.source == "ACL":
            properties["Source"] = {"select": {"name": paper.source}}

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
                parent={"database_id": db_id},
                properties=properties,
            )
            results.append({"title": paper.title, "notion_url": page["url"]})
            existing_urls.add(paper.url)  # track within this run too
        except Exception as e:
            results.append({"title": paper.title, "error": str(e)})

    return results


def sync_arxiv_to_notion(papers: list[Paper]) -> list[dict]:
    """Push arxiv papers to the dedicated arxiv Notion database.

    Skips papers whose URL already exists.
    """
    client = get_notion_client()
    db_id = os.environ.get("NOTION_ARXIV_DATABASE_ID", "e9b153737d79435e8aa23721899e0ba0")

    existing_urls = _get_existing_urls(client, db_id)
    results = []

    for paper in papers:
        if paper.url in existing_urls:
            results.append({"title": paper.title, "skipped": "already exists"})
            continue

        arxiv_id = _extract_arxiv_id(paper.url)

        properties = {
            "Title": {"title": [{"text": {"content": paper.title[:2000]}}]},
            "Authors": {"rich_text": [{"text": {"content": ", ".join(paper.authors)[:2000]}}]},
            "URL": {"url": paper.url if paper.url else None},
            "Abstract": {"rich_text": [{"text": {"content": paper.abstract[:2000]}}]},
            "Status": {"select": {"name": "New"}},
        }

        if arxiv_id:
            properties["arxiv ID"] = {"rich_text": [{"text": {"content": arxiv_id}}]}

        if paper.published:
            properties["Published"] = {
                "date": {"start": paper.published.strftime("%Y-%m-%d")}
            }

        if paper.topics:
            # Split into Categories (cs.XX) and Topics (semantic labels)
            categories = [t for t in paper.topics if t.startswith("cs.")]
            topics = [t for t in paper.topics if not t.startswith("cs.")]
            if categories:
                properties["Categories"] = {
                    "multi_select": [{"name": c[:100]} for c in categories[:10]]
                }
            if topics:
                properties["Topics"] = {
                    "multi_select": [{"name": t[:100]} for t in topics[:10]]
                }

        try:
            page = client.pages.create(
                parent={"database_id": db_id},
                properties=properties,
            )
            results.append({"title": paper.title, "notion_url": page["url"]})
            existing_urls.add(paper.url)
        except Exception as e:
            results.append({"title": paper.title, "error": str(e)})

    return results
