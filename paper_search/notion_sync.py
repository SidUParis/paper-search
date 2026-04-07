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


def _get_existing_urls(client, data_source_id: str) -> set[str]:
    """Fetch all existing paper URLs from a Notion data source to avoid duplicates."""
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


def sync_acl_papers(papers: list[Paper], database_id: str, data_source_id: str) -> list[dict]:
    """Push ACL papers to a Notion database. Skips duplicates by URL."""
    client = get_notion_client()
    existing_urls = _get_existing_urls(client, data_source_id)
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
            "Source": {"select": {"name": "ACL"}},
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
            page = client.pages.create(parent={"database_id": database_id}, properties=properties)
            results.append({"title": paper.title, "notion_url": page["url"]})
            existing_urls.add(paper.url)
        except Exception as e:
            results.append({"title": paper.title, "error": str(e)})

    return results


def sync_arxiv_papers(papers: list[Paper], database_id: str, data_source_id: str) -> list[dict]:
    """Push arxiv papers to a Notion database. Skips duplicates by URL."""
    client = get_notion_client()
    existing_urls = _get_existing_urls(client, data_source_id)
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
            page = client.pages.create(parent={"database_id": database_id}, properties=properties)
            results.append({"title": paper.title, "notion_url": page["url"]})
            existing_urls.add(paper.url)
        except Exception as e:
            results.append({"title": paper.title, "error": str(e)})

    return results


# Backwards-compatible wrappers using default (bias) database IDs
def sync_papers_to_notion(papers: list[Paper], database_id: str | None = None) -> list[dict]:
    db = database_id or os.environ.get("NOTION_DATABASE_ID", "681c5e0e039a446f8d3224a8a70fe5f9")
    ds = "3d43ef78-5f47-4ae1-9f31-fe5b382b680f"
    return sync_acl_papers(papers, db, ds)


def sync_arxiv_to_notion(papers: list[Paper]) -> list[dict]:
    db = os.environ.get("NOTION_ARXIV_DATABASE_ID", "e9b153737d79435e8aa23721899e0ba0")
    ds = "31ff8b2a-3ee1-430a-9edc-dac225acadcf"
    return sync_arxiv_papers(papers, db, ds)
