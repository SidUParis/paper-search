"""Search papers from arxiv."""

from __future__ import annotations

import arxiv
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Paper:
    title: str
    authors: list[str]
    abstract: str
    url: str
    published: datetime | None
    source: str  # "arxiv" or "ACL"
    topics: list[str] | None = None


def search_arxiv(query: str, max_results: int = 20) -> list[Paper]:
    """Search arxiv for papers matching the query."""
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    papers = []
    for result in client.results(search):
        papers.append(
            Paper(
                title=result.title,
                authors=[a.name for a in result.authors],
                abstract=result.summary,
                url=result.entry_id,
                published=result.published,
                source="arxiv",
                topics=list(result.categories) if result.categories else None,
            )
        )
    return papers


def search_arxiv_recent(category: str = "cs.CL", days: int = 7, max_results: int = 30) -> list[Paper]:
    """Search arxiv for recent papers in a category."""
    client = arxiv.Client()
    search = arxiv.Search(
        query=f"cat:{category}",
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )

    papers = []
    for result in client.results(search):
        papers.append(
            Paper(
                title=result.title,
                authors=[a.name for a in result.authors],
                abstract=result.summary,
                url=result.entry_id,
                published=result.published,
                source="arxiv",
                topics=list(result.categories) if result.categories else None,
            )
        )
    return papers
