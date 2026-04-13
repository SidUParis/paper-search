"""AI agent powered by OpenRouter for intelligent paper search."""

from __future__ import annotations

import os
import json
import time
from openai import OpenAI
from paper_search.arxiv_source import Paper, search_arxiv, search_arxiv_recent
from paper_search.acl_source import search_acl, search_acl_by_venue
from paper_search.notion_sync import sync_papers_to_notion
from paper_search.markdown import papers_to_markdown, save_markdown

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_arxiv",
            "description": "Search arxiv for papers matching a query. Good for broad keyword searches across all of arxiv.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (arxiv query syntax supported, e.g. 'ti:transformer AND abs:attention')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_arxiv_recent",
            "description": "Get recent papers from an arxiv category, sorted by submission date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "arxiv category (e.g. 'cs.CL' for NLP, 'cs.AI', 'cs.LG')",
                        "default": "cs.CL",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 30)",
                        "default": 30,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_acl",
            "description": "Search ACL Anthology for NLP/CL papers by keyword. Covers ACL, EMNLP, NAACL, EACL, COLING, and other *CL venues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keywords (matched against title and abstract)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_acl_by_venue",
            "description": "Search ACL Anthology papers by venue name and optional year.",
            "parameters": {
                "type": "object",
                "properties": {
                    "venue": {
                        "type": "string",
                        "description": "Venue identifier (e.g. 'acl', 'emnlp', 'naacl', 'eacl', 'coling')",
                    },
                    "year": {
                        "type": "integer",
                        "description": "Filter by year (optional)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["venue"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_results",
            "description": "Save the collected papers as a markdown report and optionally sync to Notion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "papers_json": {
                        "type": "string",
                        "description": "JSON array of paper objects with keys: title, authors, abstract, url, published, source, topics",
                    },
                    "query": {
                        "type": "string",
                        "description": "The original search query (used as report title)",
                    },
                    "sync_notion": {
                        "type": "boolean",
                        "description": "Whether to also sync results to Notion (default true)",
                        "default": True,
                    },
                },
                "required": ["papers_json", "query"],
            },
        },
    },
]

SYSTEM_PROMPT = """\
You are a research paper discovery assistant. Your job is to help find relevant \
academic papers from arxiv and ACL Anthology based on the user's research interests.

When the user describes a topic:
1. Search BOTH arxiv and ACL Anthology for relevant papers
2. Combine and deduplicate results
3. Rank by relevance and summarize key findings
4. Save the results as markdown and sync to Notion

Use the search tools to find papers, then use save_results to persist them.
Be thorough — try different query formulations if initial results are sparse.
For NLP/CL topics, ACL Anthology is especially valuable alongside arxiv.
"""


def _execute_tool(name: str, args: dict) -> str:
    """Execute a tool call and return the result as a string."""
    if name == "search_arxiv":
        papers = search_arxiv(args["query"], args.get("max_results", 20))
        return json.dumps([_paper_to_dict(p) for p in papers], default=str)

    elif name == "search_arxiv_recent":
        papers = search_arxiv_recent(
            args.get("category", "cs.CL"), args.get("max_results", 30)
        )
        return json.dumps([_paper_to_dict(p) for p in papers], default=str)

    elif name == "search_acl":
        papers = search_acl(args["query"], args.get("max_results", 20))
        return json.dumps([_paper_to_dict(p) for p in papers], default=str)

    elif name == "search_acl_by_venue":
        papers = search_acl_by_venue(
            args["venue"], args.get("year"), args.get("max_results", 20)
        )
        return json.dumps([_paper_to_dict(p) for p in papers], default=str)

    elif name == "save_results":
        papers_data = json.loads(args["papers_json"])
        papers = [_dict_to_paper(d) for d in papers_data]
        query = args["query"]

        md = papers_to_markdown(papers, query)
        filepath = save_markdown(md)
        result = {"markdown_path": filepath, "paper_count": len(papers)}

        if args.get("sync_notion", True):
            try:
                notion_results = sync_papers_to_notion(papers)
                result["notion_synced"] = len([r for r in notion_results if "error" not in r])
                result["notion_errors"] = len([r for r in notion_results if "error" in r])
            except Exception as e:
                result["notion_error"] = str(e)

        return json.dumps(result)

    return json.dumps({"error": f"Unknown tool: {name}"})


def _paper_to_dict(paper: Paper) -> dict:
    return {
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "url": paper.url,
        "published": paper.published.isoformat() if paper.published else None,
        "source": paper.source,
        "topics": paper.topics,
    }


def _dict_to_paper(d: dict) -> Paper:
    from datetime import datetime

    published = None
    if d.get("published"):
        try:
            published = datetime.fromisoformat(d["published"])
        except (ValueError, TypeError):
            pass

    return Paper(
        title=d.get("title", ""),
        authors=d.get("authors", []),
        abstract=d.get("abstract", ""),
        url=d.get("url", ""),
        published=published,
        source=d.get("source", "unknown"),
        topics=d.get("topics"),
    )


class PaperAgent:
    """AI agent that orchestrates paper search using OpenRouter."""

    def __init__(self, model: str | None = None):
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not set in .env")

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = model or os.environ.get("OPENROUTER_MODEL", "stepfun/step-3.5-flash:free")
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def chat(self, user_message: str, max_steps: int = 8) -> str:
        """Send a message and let the agent work through tool calls.

        Returns the final assistant text response.
        """
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(max_steps):
            response = None
            for attempt in range(5):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=self.messages,
                        tools=TOOLS,
                        tool_choice="auto",
                    )
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < 4:
                        wait = (attempt + 1) * 15
                        yield_status(f"  -> model rate-limited, retrying in {wait}s")
                        time.sleep(wait)
                        continue
                    raise

            if response is None:
                return "Model call failed after retries."

            message = response.choices[0].message
            self.messages.append(message.model_dump())

            if not message.tool_calls:
                return message.content or ""

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                yield_status(f"  -> calling {fn_name}({_summarize_args(fn_args)})")

                result = _execute_tool(fn_name, fn_args)

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        return "Reached maximum steps. Results may be partial."


def _summarize_args(args: dict) -> str:
    """Short summary of tool args for status display."""
    parts = []
    for k, v in args.items():
        if k == "papers_json":
            parts.append(f"{k}=[...]")
        elif isinstance(v, str) and len(v) > 40:
            parts.append(f'{k}="{v[:37]}..."')
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


# Simple callback for status messages — overridden by CLI
_status_callback = None


def yield_status(msg: str):
    if _status_callback:
        _status_callback(msg)
