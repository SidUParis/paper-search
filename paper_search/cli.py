"""CLI entry point for paper-search."""

from __future__ import annotations

import os
import sys
import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

console = Console()


@click.group()
def main():
    """AI-powered research paper discovery from arxiv & ACL Anthology."""
    pass


@main.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--model", default="openrouter/auto", help="OpenRouter model to use")
@click.option("--no-notion", is_flag=True, help="Skip Notion sync")
@click.option("--max-results", default=20, help="Max papers per source")
def search(query: tuple[str, ...], model: str, no_notion: bool, max_results: int):
    """Search for papers using the AI agent.

    Example: paper-search search transformer attention mechanism
    """
    query_str = " ".join(query)
    console.print(Panel(f"[bold]Searching:[/bold] {query_str}", style="blue"))

    from paper_search.agent import PaperAgent, _status_callback
    import paper_search.agent as agent_mod

    agent_mod._status_callback = lambda msg: console.print(f"[dim]{msg}[/dim]")

    agent = PaperAgent(model=model)

    prompt = f"Find papers about: {query_str}. Max {max_results} results per source."
    if no_notion:
        prompt += " Do NOT sync to Notion (set sync_notion=false in save_results)."

    result = agent.chat(prompt)
    console.print()
    console.print(Markdown(result))


@main.command()
@click.argument("source", type=click.Choice(["arxiv", "acl", "both"]), default="both")
@click.argument("query", nargs=-1, required=True)
@click.option("--max-results", default=20, help="Max papers to return")
@click.option("--save/--no-save", default=True, help="Save markdown report")
@click.option("--notion/--no-notion", default=True, help="Sync to Notion")
def quick(source: str, query: tuple[str, ...], max_results: int, save: bool, notion: bool):
    """Quick search without the AI agent — direct source query.

    Example: paper-search quick both "large language models"
    """
    query_str = " ".join(query)
    console.print(Panel(f"[bold]Quick search:[/bold] {query_str} [dim]({source})[/dim]", style="green"))

    papers = []

    if source in ("arxiv", "both"):
        console.print("[dim]Searching arxiv...[/dim]")
        from paper_search.arxiv_source import search_arxiv
        papers.extend(search_arxiv(query_str, max_results))

    if source in ("acl", "both"):
        console.print("[dim]Searching ACL Anthology...[/dim]")
        from paper_search.acl_source import search_acl
        try:
            papers.extend(search_acl(query_str, max_results))
        except ImportError as e:
            console.print(f"[yellow]ACL Anthology not available: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]ACL search error: {e}[/yellow]")

    console.print(f"\n[bold]{len(papers)} papers found[/bold]\n")

    for i, p in enumerate(papers, 1):
        console.print(f"[bold]{i}.[/bold] {p.title}")
        console.print(f"   [dim]{', '.join(p.authors[:3])}{'...' if len(p.authors) > 3 else ''}[/dim]")
        console.print(f"   [blue]{p.url}[/blue]")
        console.print(f"   [dim]{p.source} | {p.published.strftime('%Y-%m-%d') if p.published else 'N/A'}[/dim]")
        console.print()

    if save and papers:
        from paper_search.markdown import papers_to_markdown, save_markdown
        md = papers_to_markdown(papers, query_str)
        path = save_markdown(md)
        console.print(f"[green]Saved to {path}[/green]")

    if notion and papers:
        try:
            from paper_search.notion_sync import sync_papers_to_notion
            results = sync_papers_to_notion(papers)
            synced = len([r for r in results if "error" not in r])
            console.print(f"[green]Synced {synced}/{len(papers)} to Notion[/green]")
        except Exception as e:
            console.print(f"[yellow]Notion sync skipped: {e}[/yellow]")


@main.command()
@click.option("--category", default="cs.CL", help="arxiv category")
@click.option("--max-results", default=30, help="Max papers")
@click.option("--save/--no-save", default=True, help="Save markdown report")
@click.option("--notion/--no-notion", default=True, help="Sync to Notion")
def recent(category: str, max_results: int, save: bool, notion: bool):
    """Get recent papers from an arxiv category.

    Example: paper-search recent --category cs.CL
    """
    console.print(Panel(f"[bold]Recent papers:[/bold] {category}", style="cyan"))

    from paper_search.arxiv_source import search_arxiv_recent
    papers = search_arxiv_recent(category, max_results=max_results)

    console.print(f"\n[bold]{len(papers)} recent papers[/bold]\n")

    for i, p in enumerate(papers, 1):
        console.print(f"[bold]{i}.[/bold] {p.title}")
        console.print(f"   [dim]{', '.join(p.authors[:3])}{'...' if len(p.authors) > 3 else ''}[/dim]")
        console.print(f"   [dim]{p.published.strftime('%Y-%m-%d') if p.published else 'N/A'}[/dim]")
        console.print()

    if save and papers:
        from paper_search.markdown import papers_to_markdown, save_markdown
        md = papers_to_markdown(papers, f"Recent: {category}")
        path = save_markdown(md)
        console.print(f"[green]Saved to {path}[/green]")

    if notion and papers:
        try:
            from paper_search.notion_sync import sync_papers_to_notion
            results = sync_papers_to_notion(papers)
            synced = len([r for r in results if "error" not in r])
            console.print(f"[green]Synced {synced}/{len(papers)} to Notion[/green]")
        except Exception as e:
            console.print(f"[yellow]Notion sync skipped: {e}[/yellow]")


if __name__ == "__main__":
    main()
