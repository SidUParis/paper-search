"""LLM refine/reranking for the private reader workbench."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable

from paper_search.reader_context import related_papers
from paper_search.reader_models import ReaderModelRegistry, build_chat_request_kwargs

SYSTEM_PROMPT = """You are Sidney's private paper-library reranker.
Score papers for the user's research interests, especially LLM bias/fairness, BBQ/FrenchBBQ/MultilingualBBQ, evaluation methodology, sycophancy, memory bias, and related-work usefulness.
Return only strict JSON. Do not include markdown.
""".strip()


def _load_papers(site_dir: Path | str) -> list[dict[str, Any]]:
    path = Path(site_dir) / "data" / "papers.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _paper_brief(paper: dict[str, Any], idx: int) -> str:
    tags = ", ".join(str(t) for t in (paper.get("tags") or [])[:8]) if isinstance(paper.get("tags"), list) else ""
    summary = str(paper.get("zh_brief") or paper.get("tldr") or paper.get("summary") or paper.get("abstract") or "")[:900]
    return (
        f"[{idx}] paper_id: {paper.get('paper_id')}\n"
        f"Title: {paper.get('title')}\n"
        f"Topic/source: {paper.get('topic_slug')} / {paper.get('source_label') or paper.get('venue')}\n"
        f"Tags: {tags}\n"
        f"Summary: {summary}"
    )


def _candidate_papers(site_dir: Path | str, query: str, limit: int) -> list[dict[str, Any]]:
    matches = related_papers(site_dir, query, top_k=max(limit, min(40, limit * 3)))
    all_papers = _load_papers(site_dir)
    seen = {str(p.get("paper_id")) for p in matches}
    filled = list(matches)
    for paper in all_papers:
        if len(filled) >= limit:
            break
        paper_id = str(paper.get("paper_id"))
        if paper_id not in seen:
            filled.append(paper)
            seen.add(paper_id)
    return filled[:limit]


def build_ranking_messages(site_dir: Path | str, query: str, candidate_limit: int = 30) -> list[dict[str, str]]:
    query = query.strip()
    if not query:
        raise ValueError("query is required")
    candidate_limit = max(1, min(int(candidate_limit), 60))
    candidates = _candidate_papers(site_dir, query, candidate_limit)
    candidate_text = "\n\n".join(_paper_brief(paper, idx) for idx, paper in enumerate(candidates, start=1))
    user = f"""User research interest / search intent:
{query}

Candidate papers from the private library:
{candidate_text}

Return strict JSON with this exact shape:
{{
  "results": [
    {{"paper_id": "...", "score": 0.0, "reason": "中文解释为什么相关/不相关", "suggested_action": "read|skim|skip"}}
  ]
}}

Rules:
- score must be between 0 and 1.
- Rank most relevant first.
- Prefer papers that directly help the user's PhD: LLM bias, fairness benchmarks, BBQ variants, multilingual evaluation, sycophancy/memory bias.
- Reasons should be concise Chinese.
- Use only paper_ids shown above.
""".strip()
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _default_client_factory(**kwargs: Any) -> Any:
    from openai import OpenAI

    return OpenAI(**kwargs)


def _extract_json(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I).strip()
        clean = re.sub(r"\s*```$", "", clean).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise ValueError("model did not return JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("ranking JSON must be an object")
    return data


def _response_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError("unexpected ranking response shape") from exc
    return str(content or "").strip()


def rank_papers_with_llm(
    registry: ReaderModelRegistry,
    site_dir: Path | str,
    payload: dict[str, Any],
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Use a configured OpenAI-compatible model to score and rank library papers."""

    query = str(payload.get("query") or payload.get("question") or payload.get("message") or "").strip()
    if not query:
        raise ValueError("query is required")
    limit = max(1, min(int(payload.get("limit") or 12), 30))
    candidate_limit = max(limit, min(int(payload.get("candidate_limit") or 30), 60))
    provider_id = str(payload.get("provider_id") or "deepseek").strip()
    model = str(payload.get("model") or "").strip()

    messages = build_ranking_messages(site_dir, query, candidate_limit=candidate_limit)
    kwargs = build_chat_request_kwargs(
        registry,
        provider_id=provider_id,
        model=model,
        messages=messages,
        max_tokens=max(512, min(int(payload.get("max_tokens") or 2200), 4000)),
    )
    base_url = str(kwargs.pop("base_url"))
    api_key = str(kwargs.pop("api_key"))
    selected_model = str(kwargs["model"])
    client = (client_factory or _default_client_factory)(base_url=base_url, api_key=api_key)
    raw = _response_text(client.chat.completions.create(**kwargs))
    parsed = _extract_json(raw)
    papers_by_id = {str(p.get("paper_id")): p for p in _load_papers(site_dir)}
    results: list[dict[str, Any]] = []
    for item in parsed.get("results") or []:
        if not isinstance(item, dict):
            continue
        paper_id = str(item.get("paper_id") or "").strip()
        if paper_id not in papers_by_id:
            continue
        try:
            score = float(item.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        results.append(
            {
                "paper_id": paper_id,
                "score": max(0.0, min(score, 1.0)),
                "reason": str(item.get("reason") or "").strip(),
                "suggested_action": str(item.get("suggested_action") or "skim").strip(),
                "paper": papers_by_id[paper_id],
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return {"query": query, "provider_id": provider_id, "model": selected_model, "results": results[:limit]}
