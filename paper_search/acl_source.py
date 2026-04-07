"""Search papers from ACL Anthology."""

from __future__ import annotations

from paper_search.arxiv_source import Paper


def search_acl(query: str, max_results: int = 20) -> list[Paper]:
    """Search ACL Anthology for papers matching the query.

    Uses the acl-anthology Python package.
    """
    try:
        from acl_anthology import Anthology
    except ImportError:
        raise ImportError(
            "acl-anthology package required: pip install acl-anthology"
        )

    anthology = Anthology.from_repo()
    results = []

    query_lower = query.lower()
    query_terms = query_lower.split()

    for volume in anthology.volumes():
        for paper in volume.papers():
            title_str = str(paper.title) if paper.title else ""
            abstract_str = ""
            if hasattr(paper, "abstract") and paper.abstract:
                abstract_str = str(paper.abstract)

            text = (title_str + " " + abstract_str).lower()
            if all(term in text for term in query_terms):
                authors = []
                if paper.authors:
                    for author in paper.authors:
                        name = str(author.name) if hasattr(author, "name") else str(author)
                        authors.append(name)

                published = None
                if hasattr(paper, "year") and paper.year:
                    from datetime import datetime
                    try:
                        published = datetime(int(paper.year), 1, 1)
                    except (ValueError, TypeError):
                        pass

                url = f"https://aclanthology.org/{paper.full_id}/" if hasattr(paper, "full_id") else ""

                results.append(
                    Paper(
                        title=title_str,
                        authors=authors,
                        abstract=abstract_str[:500],
                        url=url,
                        published=published,
                        source="ACL",
                        topics=None,
                    )
                )
                if len(results) >= max_results:
                    return results

    return results


def search_acl_by_venue(venue: str, year: int | None = None, max_results: int = 20) -> list[Paper]:
    """Search ACL Anthology by venue (e.g. 'acl', 'emnlp', 'naacl')."""
    try:
        from acl_anthology import Anthology
    except ImportError:
        raise ImportError(
            "acl-anthology package required: pip install acl-anthology"
        )

    anthology = Anthology.from_repo()
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
            title_str = str(paper.title) if paper.title else ""
            abstract_str = ""
            if hasattr(paper, "abstract") and paper.abstract:
                abstract_str = str(paper.abstract)

            authors = []
            if paper.authors:
                for author in paper.authors:
                    name = str(author.name) if hasattr(author, "name") else str(author)
                    authors.append(name)

            published = None
            if hasattr(paper, "year") and paper.year:
                from datetime import datetime
                try:
                    published = datetime(int(paper.year), 1, 1)
                except (ValueError, TypeError):
                    pass

            url = f"https://aclanthology.org/{paper.full_id}/" if hasattr(paper, "full_id") else ""

            results.append(
                Paper(
                    title=title_str,
                    authors=authors,
                    abstract=abstract_str[:500],
                    url=url,
                    published=published,
                    source="ACL",
                    topics=None,
                )
            )
            if len(results) >= max_results:
                return results

    return results
