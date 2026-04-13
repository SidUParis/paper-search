"""AI-powered paper summarization using OpenRouter (Qwen)."""

from __future__ import annotations

import os
import re
import time
import json
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
    model = os.environ.get("OPENROUTER_MODEL", "stepfun/step-3.5-flash:free")
    return client, model


def _clean_summary_output(text: str) -> str:
    cleaned = text.strip()
    for marker in ("**RQ**:", "RQ:"):
        idx = cleaned.find(marker)
        if idx != -1:
            cleaned = cleaned[idx:]
            break

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if cleaned.startswith("RQ:"):
        cleaned = cleaned.replace("RQ:", "**RQ**:", 1)
    return cleaned


def _looks_like_final_summary(text: str) -> bool:
    lower = text.lower()
    required_markers = ["**rq**:", "**idea**:", "**method**:", "**theory**:", "**results**:"]
    if not all(marker in lower for marker in required_markers):
        return False

    forbidden = [
        "we need to summarize",
        "provide 1-2 sentences",
        "provide.",
        "theoretical grounding?",
        "read the paper text",
        "main research question:",
        "actually table",
        "wait table",
        "now craft",
        "so we can summarize",
        "could say n/a",
    ]
    if any(bad in lower for bad in forbidden):
        return False

    pattern = re.compile(
        r"\*\*RQ\*\*:\s*(?P<rq>.*?)\s*\*\*Idea\*\*:\s*(?P<idea>.*?)\s*\*\*Method\*\*:\s*(?P<method>.*?)\s*\*\*Theory\*\*:\s*(?P<theory>.*?)\s*\*\*Results\*\*:\s*(?P<results>.*)",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        return False

    sections = {k: v.strip() for k, v in match.groupdict().items()}
    if len(sections["rq"]) < 20 or len(sections["idea"]) < 20 or len(sections["method"]) < 40:
        return False
    if len(sections["results"]) < 20:
        return False
    if sections["results"].endswith(":"):
        return False
    return True


def _prepare_fulltext_excerpt(full_text: str, max_chars: int) -> str:
    text = full_text.strip()
    if len(text) <= max_chars:
        return text

    head_chars = int(max_chars * 0.67)
    tail_chars = max_chars - head_chars
    head = text[:head_chars].rstrip()
    tail = text[-tail_chars:].lstrip()
    return (
        "[BEGINNING OF PAPER]\n"
        f"{head}\n\n"
        "[MIDDLE OMITTED FOR BREVITY]\n\n"
        "[ENDING OF PAPER]\n"
        f"{tail}"
    )


def _call_summary_model(title: str, content: str, *, mode: str, max_retries: int = 5) -> str:
    client, model = get_llm_client()

    if mode == "fulltext":
        system_prompt = (
            "You are a research paper analyst. You will be given a paper title and extracted full paper text. "
            "Summarize the paper only from the provided paper text, not from prior knowledge. "
            "Return only the final formatted summary. Do not include analysis, hidden reasoning, planning notes, or preambles like 'we need to summarize'. "
            "Produce exactly these sections:\n\n"
            "**RQ**: The main research question or problem addressed (1-2 sentences)\n"
            "**Idea**: The core idea or proposed approach (1-2 sentences)\n"
            "**Method**: The methodology — models, datasets, techniques used (2-3 sentences)\n"
            "**Theory**: Theoretical grounding or motivation, if any (1 sentence, or 'N/A')\n"
            "**Results**: Key findings and their significance (2-3 sentences)\n\n"
            "Be precise and factual. If some detail is not present in the provided full text, say N/A rather than guessing. Keep the total under 220 words."
        )
        user_content = f"Title: {title}\n\nPaper text:\n{content}"
        max_tokens = 600
    else:
        system_prompt = SUMMARY_PROMPT + "\n\nReturn only the final formatted summary with the requested sections."
        user_content = f"Title: {title}\n\nAbstract: {content}"
        max_tokens = 500

    if "gemma" in model.lower():
        messages = [
            {
                "role": "user",
                "content": f"{system_prompt}\n\n{user_content}",
            }
        ]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            if response.choices:
                cleaned = _clean_summary_output(response.choices[0].message.content or "")
                if _looks_like_final_summary(cleaned):
                    return cleaned
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                raise ValueError(f"Model returned non-final summary output: {cleaned[:200]}")
            return ""
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = (attempt + 1) * 15  # longer backoff for free models
                time.sleep(wait)
            else:
                raise


def summarize_paper(title: str, abstract: str, max_retries: int = 5) -> str:
    """Generate a structured summary for a single paper from abstract only."""
    return _call_summary_model(title, abstract, mode="abstract", max_retries=max_retries)


def summarize_full_text(title: str, full_text: str, max_retries: int = 5, max_chars: int = 24000) -> str:
    """Generate a structured summary for a single paper from extracted full text."""
    clipped = _prepare_fulltext_excerpt(full_text, max_chars=max_chars)
    return _call_summary_model(title, clipped, mode="fulltext", max_retries=max_retries)


def summarize_full_text_zh_brief_and_limitations(
    title: str,
    full_text: str,
    max_retries: int = 5,
    max_chars: int = 24000,
) -> dict:
    """Generate Obsidian-specific extras (Chinese brief + limitations) from extracted full text.

    Returns:
      {"zh_brief": str, "limitations": list[str]}
    """
    clipped = _prepare_fulltext_excerpt(full_text, max_chars=max_chars)
    client, model = get_llm_client()

    system_prompt = (
        "你是一个严谨的 NLP/LLM 论文分析助手。你会得到论文标题和论文全文抽取文本。\n"
        "请只根据给定的全文文本回答，不要用外部知识，不要猜测。\n\n"
        "请输出严格的 JSON（不要 markdown code block），包含两个字段：\n"
        "- zh_brief: 中文口语化简述（3-6 句，说明问题、方法、主要结论）\n"
        "- limitations: 数组，每项是一条限制/不足/适用边界（3-7 条，尽量来自文中 limitations/讨论；若文中未明确写，写 '文中未明确陈述限制：...' 并说明缺失点）\n\n"
        "要求：内容要可追溯到给定文本；不要编造实验结果或数据集。"
    )

    user_content = f"Title: {title}\n\nPaper text:\n{clipped}"

    if "gemma" in model.lower():
        messages = [{"role": "user", "content": f"{system_prompt}\n\n{user_content}"}]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=700,
                temperature=0.2,
            )
            text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
            data = json.loads(text)
            zh_brief = (data.get("zh_brief") or "").strip()
            limitations = data.get("limitations") or []
            if not isinstance(limitations, list):
                limitations = []
            limitations = [str(x).strip() for x in limitations if str(x).strip()]
            # basic sanity
            if len(zh_brief) < 20:
                raise ValueError(f"zh_brief too short: {zh_brief[:80]}")
            return {"zh_brief": zh_brief, "limitations": limitations}
        except Exception as e:
            last_err = e
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 10)
                continue
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise

    raise last_err  # pragma: no cover


def summarize_papers_in_notion(data_source_id: str, database_id: str, batch_size: int = 10, delay: float = 3.0) -> dict:
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
