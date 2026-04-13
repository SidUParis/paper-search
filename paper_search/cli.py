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
@click.option("--model", default=None, help="OpenRouter model (default: stepfun/step-3.5-flash:free)")
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


def _render_fulltext_events(events):
    for event in events:
        if event.get("total"):
            console.print()
            console.print(f"[bold]Model:[/bold] {event['model']}")
            console.print(
                f"[bold]Done.[/bold] {event['success']} summarized, "
                f"{event['errors']} errors, {event['rate_limits']} rate-limits, "
                f"{event['fulltext_failures']} fulltext failures, {event['skipped']} skipped"
            )
            for key, count in sorted(event["breakdown"].items()):
                console.print(f"  {key}: {count}")
            break
        if event.get("status") == "done":
            console.print(f"  [green]✓[/green] {event['title'][:90]}")
            console.print(f"    [dim]cached full text:[/dim] {event.get('cache_path', '')}")
            console.print(f"    [dim]obsidian note:[/dim] {event.get('obsidian_note', '')}")
        elif event.get("status") == "skip":
            console.print(f"  [yellow]-[/yellow] {event['title'][:90]} [dim]({event.get('reason', 'skip')})[/dim]")
        elif event.get("status") == "error":
            console.print(f"  [red]✗[/red] {event['title'][:90]}: {event.get('error', '')[:120]}")


@main.command("summarize-fulltext")
@click.argument("topic_slug")
@click.option("--source", type=click.Choice(["all", "acl", "arxiv", "scholar"]), default="all")
@click.option("--limit", default=10, help="Max papers to summarize successfully in this run")
@click.option("--force-refresh", is_flag=True, help="Re-fetch PDFs/full text even if cached locally")
@click.option("--overwrite", is_flag=True, help="Replace existing Summary values instead of skipping them")
def summarize_fulltext(topic_slug: str, source: str, limit: int, force_refresh: bool, overwrite: bool):
    """Summarize already-synced Notion papers using fetched full paper text, not just abstracts."""
    from paper_search.fulltext_pipeline import summarize_topic_fulltext

    console.print(Panel(f"[bold]Full-text summarization:[/bold] {topic_slug}", style="magenta"))
    _render_fulltext_events(summarize_topic_fulltext(topic_slug, source=source, limit=limit, force_refresh=force_refresh, overwrite=overwrite))


@main.command("summarize-fulltext-all")
@click.option("--source", type=click.Choice(["all", "acl", "arxiv", "scholar"]), default="all")
@click.option("--limit", default=10, help="Global max papers to summarize successfully in this run")
@click.option("--force-refresh", is_flag=True, help="Re-fetch PDFs/full text even if cached locally")
@click.option("--overwrite", is_flag=True, help="Replace existing Summary values instead of skipping them")
def summarize_fulltext_all(source: str, limit: int, force_refresh: bool, overwrite: bool):
    """Summarize already-synced Notion papers across all topics using full paper text."""
    from paper_search.fulltext_pipeline import summarize_all_topics_fulltext

    console.print(Panel("[bold]Full-text summarization: all topics[/bold]", style="magenta"))
    _render_fulltext_events(summarize_all_topics_fulltext(limit=limit, source=source, force_refresh=force_refresh, overwrite=overwrite))


@main.command("review-init")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_init(config_path: str):
    """Validate a review project config and initialize its local state."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, initialize_review

    project = load_review_project(config_path)
    review_dir, state_path = initialize_review(project)
    console.print(Panel(f"[bold]Review project initialized:[/bold] {project.review_project_name}", style="cyan"))
    console.print(f"[green]Project dir:[/green] {get_review_dir(project.review_project_id)}")
    console.print(f"[green]State:[/green] {state_path}")


def _run_review_screen(config_path: str, source: str = "all", limit: int | None = None) -> dict:
    from paper_search.review_projects import load_review_project
    from paper_search.review_notion import load_review_candidates
    from paper_search.review_screening import build_review_record, screen_candidate
    from paper_search.review_store import get_review_dir, initialize_review, load_jsonl, save_candidates, save_records, update_state

    project = load_review_project(config_path)
    initialize_review(project)
    console.print(Panel(f"[bold]Review screening:[/bold] {project.review_project_name}", style="cyan"))

    raw_candidates = load_review_candidates(project, source=source, limit=limit)
    deduped = []
    seen_keys = set()
    for candidate in raw_candidates:
        paper_id = str(candidate.get('paper_id', '')).strip().lower()
        title = str(candidate.get('title', '')).strip().lower()
        key = paper_id or title
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(candidate)
    candidates = deduped
    save_candidates(project.review_project_id, candidates)

    review_dir = get_review_dir(project.review_project_id)
    existing_records = load_jsonl(review_dir / 'records.jsonl')
    processed_page_ids = {str(r.get('notion_page_id', '')).strip() for r in existing_records if str(r.get('notion_page_id', '')).strip()}
    records = list(existing_records)

    for idx, candidate in enumerate(candidates, start=1):
        page_id = str(candidate.get('notion_page_id', '')).strip()
        if page_id and page_id in processed_page_ids:
            continue
        screening = screen_candidate(project, candidate)
        record = build_review_record(project, candidate, screening)
        records.append(record)
        if page_id:
            processed_page_ids.add(page_id)
        save_records(project.review_project_id, records)
        update_state(
            project.review_project_id,
            review_project_name=project.review_project_name,
            source_topic_slug=project.source_topic_slug,
            config_path=project.config_path,
            stage='screening_in_progress',
            candidate_count=len(candidates),
            screened_count=len(records),
            last_processed_title=candidate.get('title', '')[:200],
        )
        icon = {"include": "[green]✓[/green]", "exclude": "[red]✗[/red]", "maybe": "[yellow]?[/yellow]"}.get(record["screening_decision"], "-")
        console.print(f"  {icon} {candidate.get('title', '')[:90]}")

    update_state(
        project.review_project_id,
        review_project_name=project.review_project_name,
        source_topic_slug=project.source_topic_slug,
        config_path=project.config_path,
        stage="screened",
        candidate_count=len(candidates),
        screened_count=len(records),
    )
    console.print(f"\n[bold]Done.[/bold] {len(records)} papers screened.")
    return {"project": project, "candidates": candidates, "records": records}


@main.command("review-screen")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--source", type=click.Choice(["all", "acl", "arxiv", "scholar"]), default="all")
@click.option("--limit", default=None, type=int, help="Max candidate papers to screen")
def review_screen(config_path: str, source: str, limit: int | None):
    """Screen candidate papers from the existing corpus for one review project."""
    _run_review_screen(config_path, source=source, limit=limit)


@main.command("review-extract")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_extract(config_path: str):
    """Extract structured fields from included review records."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import build_extraction_row, extract_record
    from paper_search.review_store import get_review_dir, load_jsonl, save_extractions, update_state

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    records = load_jsonl(review_dir / "records.jsonl")
    included = [row for row in records if row.get("screening_decision") == "include"]
    existing_rows = load_jsonl(review_dir / 'extractions.jsonl')
    extracted_page_ids = {str(r.get('notion_page_id', '')).strip() for r in existing_rows if str(r.get('notion_page_id', '')).strip()}
    extraction_rows = list(existing_rows)

    console.print(Panel(f"[bold]Review extraction:[/bold] {project.review_project_name}", style="cyan"))
    for record in included:
        page_id = str(record.get('notion_page_id', '')).strip()
        if page_id and page_id in extracted_page_ids:
            continue
        extraction = extract_record(project, record)
        row = build_extraction_row(project, record, extraction)
        extraction_rows.append(row)
        if page_id:
            extracted_page_ids.add(page_id)
        save_extractions(project.review_project_id, extraction_rows)
        update_state(project.review_project_id, stage='extraction_in_progress', extracted_count=len(extraction_rows), last_extracted_title=record.get('title', '')[:200])
        console.print(f"  [green]✓[/green] {record.get('title', '')[:90]}")

    save_extractions(project.review_project_id, extraction_rows)
    update_state(project.review_project_id, stage="extracted", extracted_count=len(extraction_rows))
    console.print(f"\n[bold]Done.[/bold] {len(extraction_rows)} papers extracted.")


@main.command("review-synthesize")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_synthesize(config_path: str):
    """Generate a markdown synthesis from extracted review records."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, save_synthesis, update_state
    from paper_search.review_synthesis import synthesize_review

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    rows = load_jsonl(review_dir / "extractions.jsonl")

    console.print(Panel(f"[bold]Review synthesis:[/bold] {project.review_project_name}", style="cyan"))
    markdown_text = synthesize_review(project, rows)
    path = save_synthesis(project.review_project_id, markdown_text)
    update_state(project.review_project_id, stage="synthesized")
    console.print(f"[green]Saved synthesis:[/green] {path}")


@main.command("review-queue")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_queue(config_path: str):
    """Generate a prioritized reading queue from extracted review rows."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, save_reading_queue, save_reading_queue_markdown, update_state
    from paper_search.review_queue import generate_reading_queue, render_reading_queue_markdown

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    rows = load_jsonl(review_dir / "extractions.jsonl")

    console.print(Panel(f"[bold]Review reading queue:[/bold] {project.review_project_name}", style="cyan"))
    ranked_rows = generate_reading_queue(project, rows)
    queue_path = save_reading_queue(project.review_project_id, ranked_rows)
    markdown_path = save_reading_queue_markdown(project.review_project_id, render_reading_queue_markdown(project, ranked_rows))
    update_state(project.review_project_id, stage="queue_generated", reading_queue_path=str(queue_path), reading_queue_markdown_path=str(markdown_path))
    console.print(f"[green]Saved reading queue:[/green] {queue_path}")
    console.print(f"[green]Saved queue markdown:[/green] {markdown_path}")


@main.command("review-gap-summary")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_gap_summary(config_path: str):
    """Generate project-level research gap summary + structured topic signals."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, save_gap_summary, save_topic_signals, update_state
    from paper_search.review_gap_summary import aggregate_review_signals, render_gap_summary_markdown
    from paper_search.review_queue import generate_reading_queue

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    rows = load_jsonl(review_dir / "extractions.jsonl")
    ranked_rows = generate_reading_queue(project, rows)

    console.print(Panel(f"[bold]Review gap summary:[/bold] {project.review_project_name}", style="cyan"))
    signals = aggregate_review_signals(project, ranked_rows)
    markdown_path = save_gap_summary(project.review_project_id, render_gap_summary_markdown(project, signals))
    signals_path = save_topic_signals(project.review_project_id, signals)
    update_state(project.review_project_id, stage="gap_summary_generated", gap_summary_path=str(markdown_path), topic_signals_path=str(signals_path))
    console.print(f"[green]Saved gap summary:[/green] {markdown_path}")
    console.print(f"[green]Saved topic signals:[/green] {signals_path}")


@main.command("review-digest")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--period", type=click.Choice(["daily", "weekly"]), default="weekly")
def review_digest(config_path: str, period: str):
    """Generate a short operational digest from extracted review rows."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, save_digest, update_state
    from paper_search.review_digest import generate_review_digest

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    rows = load_jsonl(review_dir / "extractions.jsonl")
    synthesis_text = (review_dir / "synthesis.md").read_text(encoding="utf-8") if (review_dir / "synthesis.md").exists() else ""
    idea_text = (review_dir / "idea_slate.md").read_text(encoding="utf-8") if (review_dir / "idea_slate.md").exists() else ""

    console.print(Panel(f"[bold]Review digest:[/bold] {project.review_project_name}", style="cyan"))
    markdown_text = generate_review_digest(project, rows, synthesis_text=synthesis_text, idea_slate_text=idea_text, period=period)
    path = save_digest(project.review_project_id, markdown_text, period=period)
    update_state(project.review_project_id, stage="digest_generated", digest_path=str(path), digest_period=period)
    console.print(f"[green]Saved digest:[/green] {path}")


@main.command("review-ideas")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_ideas(config_path: str):
    """Generate a research idea slate from review synthesis + extractions."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, save_idea_slate, update_state
    from paper_search.review_ideas import generate_idea_slate

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    rows = load_jsonl(review_dir / "extractions.jsonl")
    synthesis_path = review_dir / "synthesis.md"
    gap_summary_path = review_dir / "gap_summary.md"
    synthesis_text = synthesis_path.read_text(encoding="utf-8") if synthesis_path.exists() else ""
    gap_summary_text = gap_summary_path.read_text(encoding="utf-8") if gap_summary_path.exists() else ""

    console.print(Panel(f"[bold]Review idea slate:[/bold] {project.review_project_name}", style="cyan"))
    markdown_text = generate_idea_slate(project, rows, synthesis_text, gap_summary_text=gap_summary_text)
    path = save_idea_slate(project.review_project_id, markdown_text)
    update_state(project.review_project_id, stage="ideas_generated", idea_slate_path=str(path))
    console.print(f"[green]Saved idea slate:[/green] {path}")


@main.command("review-writeback")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_writeback(config_path: str):
    """Write review results back to the source Notion database(s)."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, update_state
    from paper_search.review_writeback import ensure_review_properties, write_review_results_to_notion

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    records = load_jsonl(review_dir / "records.jsonl")
    source_labels = {str(r.get('source_label', '')).strip() for r in records if str(r.get('source_label', '')).strip()}

    console.print(Panel(f"[bold]Review writeback:[/bold] {project.review_project_name}", style="cyan"))
    ensure_review_properties(project, source_labels=source_labels)
    stats = write_review_results_to_notion(project)
    update_state(project.review_project_id, stage="notion_synced", notion_updated=stats["updated"], notion_skipped=stats["skipped"])
    console.print(f"[green]Updated:[/green] {stats['updated']} pages")
    console.print(f"[yellow]Skipped:[/yellow] {stats['skipped']} pages")


@main.command("review-sync-obsidian")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
def review_sync_obsidian(config_path: str):
    """Sync review outputs into the local Obsidian vault."""
    from paper_search.review_projects import load_review_project
    from paper_search.review_store import get_review_dir, load_jsonl, update_state
    from paper_search.review_obsidian import sync_review_to_obsidian

    project = load_review_project(config_path)
    review_dir = get_review_dir(project.review_project_id)
    records = load_jsonl(review_dir / 'records.jsonl')
    extraction_rows = load_jsonl(review_dir / 'extractions.jsonl')
    synthesis_path = review_dir / 'synthesis.md'
    idea_path = review_dir / 'idea_slate.md'
    gap_summary_path = review_dir / 'gap_summary.md'
    reading_queue_path = review_dir / 'reading_queue.md'
    digest_path = review_dir / 'weekly_digest.md'
    synthesis_text = synthesis_path.read_text(encoding='utf-8') if synthesis_path.exists() else ''
    idea_text = idea_path.read_text(encoding='utf-8') if idea_path.exists() else ''
    gap_summary_text = gap_summary_path.read_text(encoding='utf-8') if gap_summary_path.exists() else ''
    reading_queue_text = reading_queue_path.read_text(encoding='utf-8') if reading_queue_path.exists() else ''
    digest_text = digest_path.read_text(encoding='utf-8') if digest_path.exists() else ''

    console.print(Panel(f"[bold]Review Obsidian sync:[/bold] {project.review_project_name}", style="cyan"))
    paths = sync_review_to_obsidian(
        project,
        records,
        extraction_rows,
        synthesis_text,
        idea_slate_text=idea_text,
        gap_summary_text=gap_summary_text,
        reading_queue_text=reading_queue_text,
        digest_text=digest_text,
    )
    update_state(project.review_project_id, stage='obsidian_synced', review_note_path=paths['review_note_path'], updated_paper_notes=len(paths['updated_paper_notes']))
    console.print(f"[green]Review note:[/green] {paths['review_note_path']}")
    console.print(f"[green]Paper notes updated:[/green] {len(paths['updated_paper_notes'])}")


@main.command("review-run")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--source", type=click.Choice(["all", "acl", "arxiv", "scholar"]), default="all")
@click.option("--limit", default=None, type=int, help="Max candidate papers to screen")
def review_run(config_path: str, source: str, limit: int | None):
    """Run screen -> extract -> queue -> synthesize -> gap summary -> digest -> ideas -> writeback -> obsidian sync for one review project."""
    _run_review_screen(config_path, source=source, limit=limit)
    review_extract.callback(config_path)
    review_queue.callback(config_path)
    review_synthesize.callback(config_path)
    review_gap_summary.callback(config_path)
    review_digest.callback(config_path, period='weekly')
    review_ideas.callback(config_path)
    review_writeback.callback(config_path)
    review_sync_obsidian.callback(config_path)


if __name__ == "__main__":
    main()
