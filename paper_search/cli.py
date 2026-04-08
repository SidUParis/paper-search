"""CLI entry point for paper-search."""

from __future__ import annotations

import os
import time
import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

console = Console()


@click.group()
def main():
    """AI-powered research paper discovery from arxiv & ACL Anthology."""
    pass


# ── Topic management ──────────────────────────────────────────────

@main.command()
def topics():
    """List all configured research topics."""
    from paper_search.topics import list_topics

    all_topics = list_topics()
    if not all_topics:
        console.print("[yellow]No topics configured. Add one with: paper-search add-topic[/yellow]")
        return

    table = Table(title="Research Topics")
    table.add_column("Slug", style="bold")
    table.add_column("Name")
    table.add_column("Keywords")
    table.add_column("Created")

    for slug, cfg in all_topics:
        kw = ", ".join(cfg["keywords"][:4])
        if len(cfg["keywords"]) > 4:
            kw += "..."
        table.add_row(slug, cfg["name"], kw, cfg.get("created", "?"))

    console.print(table)


@main.command("add-topic")
@click.argument("slug")
@click.argument("name")
@click.option("--keywords", "-k", required=True, help="Comma-separated search keywords")
@click.option("--arxiv-queries", "-q", required=True, help="Comma-separated arxiv queries")
@click.option("--acl-db", required=True, help="Notion ACL database ID")
@click.option("--acl-ds", required=True, help="Notion ACL data source ID")
@click.option("--arxiv-db", required=True, help="Notion arxiv database ID")
@click.option("--arxiv-ds", required=True, help="Notion arxiv data source ID")
def add_topic(slug, name, keywords, arxiv_queries, acl_db, acl_ds, arxiv_db, arxiv_ds):
    """Register a new research topic.

    Example:
        paper-search add-topic sycophancy "Sycophancy in LLMs" \\
            -k "sycophancy,sycophantic,people-pleasing" \\
            -q "sycophancy LLM,sycophantic behavior language model" \\
            --acl-db ABC123 --acl-ds DEF456 --arxiv-db GHI789 --arxiv-ds JKL012
    """
    from paper_search.topics import add_topic as _add

    topic = _add(
        slug=slug, name=name,
        keywords=[k.strip() for k in keywords.split(",")],
        arxiv_queries=[q.strip() for q in arxiv_queries.split(",")],
        acl_database_id=acl_db, acl_data_source_id=acl_ds,
        arxiv_database_id=arxiv_db, arxiv_data_source_id=arxiv_ds,
    )
    console.print(f"[green]Added topic:[/green] {topic['name']} ({slug})")


# ── Main update command ───────────────────────────────────────────

@main.command()
@click.argument("topic_slug")
@click.option("--source", type=click.Choice(["all", "acl", "arxiv", "scholar"]), default="all")
@click.option("--max-results", default=200, help="Max papers per source/query")
@click.option("--no-notion", is_flag=True, help="Skip Notion sync")
@click.option("--summarize/--no-summarize", default=True, help="AI-summarize new papers (default: on)")
def update(topic_slug: str, source: str, max_results: int, no_notion: bool, summarize: bool):
    """Search and sync papers for a topic. Safe to run daily (deduplicates).

    Sources: acl, arxiv, scholar (FAccT/NeurIPS/ICLR/ICML), or all.

    \b
    Examples:
        paper-search update bias-fairness
        paper-search update conv-summarization --source arxiv
        paper-search update bias-fairness --no-notion
    """
    from paper_search.topics import get_topic
    from paper_search.arxiv_source import search_arxiv
    from paper_search.acl_source import search_acl_by_venue
    from paper_search.notion_sync import sync_acl_papers, sync_arxiv_papers, sync_scholar_papers
    from paper_search.markdown import papers_to_markdown, save_markdown

    topic = get_topic(topic_slug)
    if not topic:
        console.print(f"[red]Topic '{topic_slug}' not found. Run: paper-search topics[/red]")
        return

    console.print(Panel(f"[bold]{topic['name']}[/bold]", style="blue"))

    seen = set()
    acl_papers = []
    arxiv_papers = []
    scholar_papers = []

    # ── ACL search ──
    if source in ("all", "acl"):
        console.print("[dim]Searching ACL Anthology...[/dim]")
        for year in topic.get("acl_years", [2025, 2026]):
            for venue in topic.get("acl_venues", []):
                papers = search_acl_by_venue(
                    venue, year=year, max_results=max_results,
                    keywords=topic["keywords"],
                )
                for p in papers:
                    key = p.title.lower().strip()
                    if key not in seen:
                        seen.add(key)
                        acl_papers.append(p)

        console.print(f"  [bold]{len(acl_papers)}[/bold] ACL papers found")

    # ── arxiv search ──
    if source in ("all", "arxiv"):
        console.print("[dim]Searching arxiv...[/dim]")
        for query in topic.get("arxiv_queries", []):
            console.print(f"  [dim]{query}[/dim]")
            try:
                papers = search_arxiv(query, max_results=max_results)
                for p in papers:
                    key = p.title.lower().strip()
                    if key not in seen:
                        seen.add(key)
                        arxiv_papers.append(p)
                time.sleep(3)
            except Exception as e:
                console.print(f"  [yellow]Error: {e}[/yellow]")
                time.sleep(10)

        console.print(f"  [bold]{len(arxiv_papers)}[/bold] arxiv papers found")

    # ── Semantic Scholar search (FAccT, NeurIPS, ICLR, ICML) ──
    if source in ("all", "scholar") and topic.get("scholar_venues"):
        console.print(f"[dim]Searching {', '.join(topic['scholar_venues'])}...[/dim]")
        from paper_search.scholar_source import search_venue
        for query in topic.get("scholar_queries", topic.get("arxiv_queries", [])):
            console.print(f"  [dim]{query}[/dim]")
            try:
                papers = search_venue(query, topic["scholar_venues"], max_results=max_results)
                for p in papers:
                    key = p.title.lower().strip()
                    if key not in seen:
                        seen.add(key)
                        scholar_papers.append(p)
            except Exception as e:
                console.print(f"  [yellow]Error: {e}[/yellow]")
            time.sleep(2)

        console.print(f"  [bold]{len(scholar_papers)}[/bold] Scholar papers found")

    # ── Save markdown ──
    all_papers = acl_papers + arxiv_papers + scholar_papers
    if all_papers:
        md = papers_to_markdown(all_papers, topic["name"])
        slug = topic_slug.replace(" ", "_")
        path = save_markdown(md, f"{slug}_latest.md")
        console.print(f"[green]Markdown: {path}[/green]")

    # ── Notion sync ──
    if not no_notion and all_papers:
        console.print("[dim]Syncing to Notion...[/dim]")

        if acl_papers:
            results = sync_acl_papers(
                acl_papers,
                topic["acl_database_id"],
                topic["acl_data_source_id"],
            )
            added = len([r for r in results if "notion_url" in r])
            skipped = len([r for r in results if "skipped" in r])
            errors = len([r for r in results if "error" in r])
            console.print(f"  ACL -> Notion: [green]+{added}[/green] new, {skipped} existing, [red]{errors} errors[/red]")

        if arxiv_papers:
            results = sync_arxiv_papers(
                arxiv_papers,
                topic["arxiv_database_id"],
                topic["arxiv_data_source_id"],
            )
            added = len([r for r in results if "notion_url" in r])
            skipped = len([r for r in results if "skipped" in r])
            errors = len([r for r in results if "error" in r])
            console.print(f"  arxiv -> Notion: [green]+{added}[/green] new, {skipped} existing, [red]{errors} errors[/red]")

        if scholar_papers and topic.get("scholar_database_id"):
            results = sync_scholar_papers(
                scholar_papers,
                topic["scholar_database_id"],
                topic["scholar_data_source_id"],
            )
            added = len([r for r in results if "notion_url" in r])
            skipped = len([r for r in results if "skipped" in r])
            errors = len([r for r in results if "error" in r])
            console.print(f"  Scholar -> Notion: [green]+{added}[/green] new, {skipped} existing, [red]{errors} errors[/red]")

    # ── AI Summarization ──
    if summarize and not no_notion:
        console.print("[dim]Generating AI summaries for unsummarized papers...[/dim]")
        from paper_search.summarizer import summarize_papers_in_notion

        dbs = [
            ("ACL", topic["acl_data_source_id"], topic["acl_database_id"]),
            ("arxiv", topic["arxiv_data_source_id"], topic["arxiv_database_id"]),
        ]
        if topic.get("scholar_data_source_id"):
            dbs.append(("Scholar", topic["scholar_data_source_id"], topic["scholar_database_id"]))
        for ds_label, ds_id, db_id in dbs:
            count = 0
            errors = 0
            for event in summarize_papers_in_notion(ds_id, db_id):
                if "total" in event:
                    # final stats
                    break
                if event.get("status") == "done":
                    count += 1
                    console.print(f"  [green]✓[/green] {event['title'][:70]}")
                elif event.get("status") == "error":
                    errors += 1
                    console.print(f"  [red]✗[/red] {event['title'][:70]}: {event.get('error', '')[:50]}")
            if count or errors:
                console.print(f"  {ds_label}: [green]{count} summarized[/green], [red]{errors} errors[/red]")
            else:
                console.print(f"  {ds_label}: all papers already summarized")

    console.print(f"\n[bold]Done.[/bold] {len(all_papers)} papers processed.")


# ── Standalone summarize command ──────────────────────────────────

@main.command()
@click.argument("topic_slug")
@click.option("--source", type=click.Choice(["both", "acl", "arxiv"]), default="both")
def summarize(topic_slug: str, source: str):
    """Generate AI summaries for papers that don't have one yet.

    \b
    Examples:
        paper-search summarize bias-fairness
        paper-search summarize conv-summarization --source acl
    """
    from paper_search.topics import get_topic
    from paper_search.summarizer import summarize_papers_in_notion

    topic = get_topic(topic_slug)
    if not topic:
        console.print(f"[red]Topic '{topic_slug}' not found. Run: paper-search topics[/red]")
        return

    console.print(Panel(f"[bold]Summarizing: {topic['name']}[/bold]", style="magenta"))

    sources = []
    if source in ("both", "acl"):
        sources.append(("ACL", topic["acl_data_source_id"], topic["acl_database_id"]))
    if source in ("both", "arxiv"):
        sources.append(("arxiv", topic["arxiv_data_source_id"], topic["arxiv_database_id"]))

    for ds_label, ds_id, db_id in sources:
        console.print(f"\n[bold]{ds_label}[/bold]")
        count = 0
        errors = 0
        for event in summarize_papers_in_notion(ds_id, db_id):
            if "total" in event:
                console.print(f"  Total in database: {event['total']}, skipped: {event['skipped']}")
                break
            if event.get("status") == "done":
                count += 1
                console.print(f"  [green]✓[/green] {event['title'][:70]}")
            elif event.get("status") == "error":
                errors += 1
                console.print(f"  [red]✗[/red] {event['title'][:70]}: {event.get('error', '')[:60]}")

        console.print(f"  [bold]{count} summarized, {errors} errors[/bold]")


# ── Quick search (no topic needed) ────────────────────────────────

@main.command()
@click.argument("source", type=click.Choice(["arxiv", "acl", "both"]), default="both")
@click.argument("query", nargs=-1, required=True)
@click.option("--max-results", default=20, help="Max papers to return")
@click.option("--save/--no-save", default=True, help="Save markdown report")
def quick(source: str, query: tuple[str, ...], max_results: int, save: bool):
    """Quick search without topic config — direct source query.

    Example: paper-search quick both "large language models"
    """
    query_str = " ".join(query)
    console.print(Panel(f"[bold]Quick search:[/bold] {query_str} [dim]({source})[/dim]", style="green"))

    papers = []

    if source in ("arxiv", "both"):
        console.print("[dim]Searching arxiv...[/dim]")
        from paper_search.arxiv_source import search_arxiv
        try:
            papers.extend(search_arxiv(query_str, max_results))
        except Exception as e:
            console.print(f"[yellow]arxiv error: {e}[/yellow]")

    if source in ("acl", "both"):
        console.print("[dim]Searching ACL Anthology...[/dim]")
        from paper_search.acl_source import search_acl
        try:
            papers.extend(search_acl(query_str, max_results))
        except Exception as e:
            console.print(f"[yellow]ACL error: {e}[/yellow]")

    console.print(f"\n[bold]{len(papers)} papers found[/bold]\n")

    for i, p in enumerate(papers, 1):
        console.print(f"[bold]{i}.[/bold] {p.title}")
        console.print(f"   [dim]{', '.join(p.authors[:3])}{'...' if len(p.authors) > 3 else ''}[/dim]")
        console.print(f"   [blue]{p.url}[/blue]")
        console.print()

    if save and papers:
        from paper_search.markdown import papers_to_markdown, save_markdown
        md = papers_to_markdown(papers, query_str)
        path = save_markdown(md)
        console.print(f"[green]Saved to {path}[/green]")


# ── AI agent search ───────────────────────────────────────────────

@main.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--model", default=None, help="OpenRouter model (default: qwen/qwen3.6-plus:free)")
def search(query: tuple[str, ...], model: str):
    """Search for papers using the AI agent.

    Example: paper-search search transformer attention mechanism
    """
    query_str = " ".join(query)
    console.print(Panel(f"[bold]AI Search:[/bold] {query_str}", style="blue"))

    from paper_search.agent import PaperAgent
    import paper_search.agent as agent_mod

    agent_mod._status_callback = lambda msg: console.print(f"[dim]{msg}[/dim]")
    agent = PaperAgent(model=model)
    result = agent.chat(f"Find papers about: {query_str}")
    console.print()
    console.print(Markdown(result))


if __name__ == "__main__":
    main()
