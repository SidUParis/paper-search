"""AI-powered paper summarization using OpenRouter (Qwen)."""

from __future__ import annotations

import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

SUMMARY_PROMPT = """\
You are a research paper analyst. Given a paper's title and abstract, produce a concise structured summary with exactly these sections:

**RQ**: The main research question or problem addressed (1-2 sentences)
**Idea**: The core idea or proposed approach (1-2 sentences)
**Method**: The methodology — models, datasets, techniques used (2-3 sentences)
**Theory**: Theoretical grounding or motivation, if any (1 sentence, or "N/A")
**Results**: Key findings and their significance (2-3 sentences)

Be precise and factual. Do not add information not in the abstract. Keep the total under 200 words."""


def get_llm_client() -> tuple[OpenAI, str]:
    """Get OpenRouter client and model name."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set in .env")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    model = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.6-plus:free")
    return client, model


def summarize_paper(title: str, abstract: str, max_retries: int = 3) -> str:
    """Generate a structured summary for a single paper."""
    client, model = get_llm_client()

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": f"Title: {title}\n\nAbstract: {abstract}"},
                ],
                max_tokens=500,
            )
            if response.choices:
                return response.choices[0].message.content or ""
            return ""
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = (attempt + 1) * 10
                time.sleep(wait)
            else:
                raise


def summarize_papers_in_notion(data_source_id: str, database_id: str, batch_size: int = 10, delay: float = 1.0) -> dict:
    """Summarize all papers in a Notion database that don't have a Summary yet.

    Returns stats: {summarized, skipped, errors}.
    """
    from paper_search.notion_sync import get_notion_client

    notion = get_notion_client()
    client, model = get_llm_client()

    # Fetch all pages
    pages = []
    start_cursor = None
    while True:
        kwargs = {"data_source_id": data_source_id, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        response = notion.data_sources.query(**kwargs)
        pages.extend(response["results"])
        if not response.get("has_more"):
            break
        start_cursor = response.get("next_cursor")

    stats = {"summarized": 0, "skipped": 0, "errors": 0, "total": len(pages)}

    for page in pages:
        props = page["properties"]

        # Skip if already has a summary
        summary_prop = props.get("Summary", {})
        existing = ""
        if summary_prop.get("rich_text"):
            existing = summary_prop["rich_text"][0].get("text", {}).get("content", "")
        if existing.strip():
            stats["skipped"] += 1
            continue

        # Extract title and abstract
        title = ""
        if props.get("Title", {}).get("title"):
            title = props["Title"]["title"][0]["text"]["content"]

        abstract = ""
        if props.get("Abstract", {}).get("rich_text"):
            abstract = props["Abstract"]["rich_text"][0]["text"]["content"]

        if not abstract:
            stats["skipped"] += 1
            continue

        # Generate summary
        try:
            summary = summarize_paper(title, abstract)

            # Update the page in Notion
            notion.pages.update(
                page_id=page["id"],
                properties={
                    "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
                },
            )
            stats["summarized"] += 1
            yield {"title": title, "status": "done"}
            time.sleep(delay)

        except Exception as e:
            stats["errors"] += 1
            yield {"title": title, "status": "error", "error": str(e)}

    yield stats
