"""Generate markdown reports from paper search results."""

from __future__ import annotations

import os
from datetime import datetime
from paper_search.arxiv_source import Paper

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def papers_to_markdown(papers: list[Paper], query: str) -> str:
    """Convert a list of papers into a markdown report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Paper Search: {query}",
        f"",
        f"*Generated: {now} | {len(papers)} papers found*",
        f"",
        "---",
        "",
    ]

    for i, paper in enumerate(papers, 1):
        authors_str = ", ".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors_str += f" et al. ({len(paper.authors)} authors)"

        pub_date = paper.published.strftime("%Y-%m-%d") if paper.published else "N/A"

        lines.extend([
            f"## {i}. {paper.title}",
            f"",
            f"- **Authors**: {authors_str}",
            f"- **Source**: {paper.source}",
            f"- **Published**: {pub_date}",
            f"- **URL**: {paper.url}",
        ])

        if paper.topics:
            lines.append(f"- **Topics**: {', '.join(paper.topics)}")

        lines.extend([
            f"",
            f"> {paper.abstract[:400]}{'...' if len(paper.abstract) > 400 else ''}",
            f"",
            "---",
            "",
        ])

    return "\n".join(lines)


def save_markdown(content: str, filename: str | None = None) -> str:
    """Save markdown content to the output directory. Returns the file path."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"papers_{timestamp}.md"

    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content)

    return filepath
