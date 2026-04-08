"""Search papers from ACL Anthology."""

from __future__ import annotations

from datetime import datetime
from paper_search.arxiv_source import Paper


def _format_author(author) -> str:
    """Extract a clean name string from an ACL Anthology author object."""
    if hasattr(author, "first") and hasattr(author, "last"):
        return f"{author.first} {author.last}"
    if hasattr(author, "name"):
        n = author.name
        if hasattr(n, "first") and hasattr(n, "last"):
            return f"{n.first} {n.last}"
        return str(n)
    return str(author)


def _paper_to_result(paper) -> Paper:
    """Convert an ACL Anthology paper object to our Paper dataclass."""
    title_str = str(paper.title) if paper.title else ""
    abstract_str = ""
    if hasattr(paper, "abstract") and paper.abstract:
        abstract_str = str(paper.abstract)

    authors = [_format_author(a) for a in paper.authors] if paper.authors else []

    published = None
    if hasattr(paper, "year") and paper.year:
        try:
            month_num = 1
            if hasattr(paper, "month") and paper.month:
                MONTHS = {
                    "january": 1, "february": 2, "march": 3, "april": 4,
                    "may": 5, "june": 6, "july": 7, "august": 8,
                    "september": 9, "october": 10, "november": 11, "december": 12,
                }
                month_num = MONTHS.get(str(paper.month).lower(), 1)
            published = datetime(int(paper.year), month_num, 1)
        except (ValueError, TypeError):
            pass

    venue_str = None
    is_findings = False
    if hasattr(paper, "full_id") and paper.full_id:
        parts = str(paper.full_id).split(".")
        if len(parts) >= 2:
            segment = parts[1]  # e.g. "findings-eacl" or "eacl-main"
            seg_parts = segment.split("-")
            if seg_parts[0].lower() == "findings" and len(seg_parts) >= 2:
                # findings-eacl -> venue=EACL, track=Findings
                venue_str = seg_parts[1].upper()
                is_findings = True
            else:
                venue_str = seg_parts[0].upper()

    url = f"https://aclanthology.org/{paper.full_id}/" if hasattr(paper, "full_id") else ""

    topics = []
    if venue_str:
        topics.append(venue_str)
    if is_findings:
        topics.append("Findings")

    return Paper(
        title=title_str,
        authors=authors,
        abstract=abstract_str[:500],
        url=url,
        published=published,
        source=venue_str or "ACL",
        topics=topics or None,
    )


def _get_anthology():
    try:
        from acl_anthology import Anthology
    except ImportError:
        raise ImportError("acl-anthology package required: pip install acl-anthology")
    return Anthology.from_repo()


def search_acl(query: str, max_results: int = 20) -> list[Paper]:
    """Search ACL Anthology for papers matching the query."""
    anthology = _get_anthology()
    results = []
    query_terms = query.lower().split()

    for volume in anthology.volumes():
        for paper in volume.papers():
            title_str = str(paper.title) if paper.title else ""
            abstract_str = str(paper.abstract) if hasattr(paper, "abstract") and paper.abstract else ""
            text = (title_str + " " + abstract_str).lower()

            if all(term in text for term in query_terms):
                results.append(_paper_to_result(paper))
                if len(results) >= max_results:
                    return results

    return results


def search_acl_by_venue(
    venue: str,
    year: int | None = None,
    max_results: int = 20,
    keywords: list[str] | None = None,
) -> list[Paper]:
    """Search ACL Anthology by venue and optional year/keywords.

    Args:
        venue: Venue identifier (e.g. 'acl', 'emnlp', 'naacl', 'eacl')
        year: Filter by year
        max_results: Maximum results to return
        keywords: Optional keyword filter on title+abstract
    """
    anthology = _get_anthology()
    results = []

    for volume in anthology.volumes():
        vol_id = str(volume.full_id) if hasattr(volume, "full_id") else ""
        if venue.lower() not in vol_id.lower():
            continue

        if year and hasattr(volume, "year"):
            try:
                if int(volume.year) != year:
                    continue
            except (ValueError, TypeError):
                continue

        for paper in volume.papers():
            if keywords:
                title_str = str(paper.title) if paper.title else ""
                abstract_str = str(paper.abstract) if hasattr(paper, "abstract") and paper.abstract else ""
                text = (title_str + " " + abstract_str).lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue

            results.append(_paper_to_result(paper))
            if len(results) >= max_results:
                return results

    return results
