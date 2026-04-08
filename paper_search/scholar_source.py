"""Search papers from Semantic Scholar API (FAccT, NeurIPS, ICLR, ICML, etc.)."""

from __future__ import annotations

import time
import requests
from datetime import datetime
from paper_search.arxiv_source import Paper

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,venue,year,abstract,authors,url,externalIds"

# Semantic Scholar returns full venue names; map them to short labels
VENUE_SHORT = {
    "conference on fairness, accountability and transparency": "FAccT",
    "conference on fairness, accountability, and transparency": "FAccT",
    "facct": "FAccT",
    "neural information processing systems": "NeurIPS",
    "neurips": "NeurIPS",
    "advances in neural information processing systems": "NeurIPS",
    "international conference on learning representations": "ICLR",
    "iclr": "ICLR",
    "international conference on machine learning": "ICML",
    "icml": "ICML",
}


def _search_scholar(
    query: str,
    venues: list[str] | None = None,
    year: str | None = None,
    limit: int = 100,
    max_retries: int = 5,
) -> list[dict]:
    """Raw Semantic Scholar search with retry on 429."""
    all_results = []
    offset = 0
    per_page = min(limit, 100)

    while offset < limit:
        params = {
            "query": query,
            "limit": per_page,
            "offset": offset,
            "fields": FIELDS,
        }
        if venues:
            params["venue"] = ",".join(venues)
        if year:
            params["year"] = year

        for attempt in range(max_retries):
            resp = requests.get(BASE_URL, params=params)
            if resp.status_code == 200:
                break
            elif resp.status_code == 429:
                wait = (attempt + 1) * 5
                time.sleep(wait)
            else:
                resp.raise_for_status()
        else:
            break  # exhausted retries

        if resp.status_code != 200:
            break

        data = resp.json()
        results = data.get("data", [])
        if not results:
            break

        all_results.extend(results)
        offset += len(results)

        if offset >= data.get("total", 0):
            break

        time.sleep(1)  # respect rate limit

    return all_results[:limit]


def _to_paper(item: dict, source_label: str = "Scholar") -> Paper:
    """Convert a Semantic Scholar result to our Paper dataclass."""
    authors = [a["name"] for a in item.get("authors", [])]

    published = None
    if item.get("year"):
        published = datetime(item["year"], 1, 1)

    raw_venue = item.get("venue", "")
    venue = VENUE_SHORT.get(raw_venue.lower(), raw_venue) if raw_venue else ""
    topics = [venue] if venue else None

    url = item.get("url", "")
    # Prefer arxiv URL if available
    ext_ids = item.get("externalIds", {})
    if ext_ids and ext_ids.get("ArXiv"):
        url = f"https://arxiv.org/abs/{ext_ids['ArXiv']}"

    return Paper(
        title=item.get("title", ""),
        authors=authors,
        abstract=item.get("abstract", "") or "",
        url=url,
        published=published,
        source=source_label,
        topics=topics,
    )


def search_venue(
    query: str,
    venues: list[str],
    max_results: int = 50,
    year: str | None = None,
) -> list[Paper]:
    """Search Semantic Scholar for papers in specific venues.

    Args:
        query: Search keywords
        venues: List of venue names (e.g. ["FAccT", "NeurIPS", "ICLR", "ICML"])
        max_results: Maximum results to return
        year: Year filter (e.g. "2024", "2024-2026")
    """
    results = _search_scholar(query, venues=venues, year=year, limit=max_results)
    return [_to_paper(r, source_label=VENUE_SHORT.get(r.get("venue", "").lower(), r.get("venue", "Scholar"))) for r in results]


def search_facct(query: str, max_results: int = 50, year: str | None = None) -> list[Paper]:
    """Search FAccT papers."""
    return search_venue(query, ["FAccT"], max_results, year)


def search_ml_conferences(
    query: str,
    max_results: int = 50,
    year: str | None = None,
    venues: list[str] | None = None,
) -> list[Paper]:
    """Search across ML conferences (NeurIPS, ICLR, ICML + optionally more).

    Default venues: NeurIPS, ICLR, ICML.
    """
    target_venues = venues or ["NeurIPS", "ICLR", "ICML"]
    return search_venue(query, target_venues, max_results, year)
