"""LLM refine/reranking for the private reader workbench."""

from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any, Callable

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


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]+", " ", str(text or "").lower())).strip()


def _tokens(text: Any) -> set[str]:
    return {token for token in _normalize(text).split() if len(token) > 2}


def _paper_search_text(paper: dict[str, Any]) -> str:
    tags = " ".join(str(t) for t in paper.get("tags") or [] if str(t).strip()) if isinstance(paper.get("tags"), list) else ""
    authors = " ".join(str(a) for a in paper.get("authors") or [] if str(a).strip()) if isinstance(paper.get("authors"), list) else ""
    fields = [
        paper.get("title"),
        authors,
        paper.get("year"),
        paper.get("display_venue") or paper.get("venue") or paper.get("source_label"),
        paper.get("topic_slug"),
        tags,
        paper.get("zh_brief"),
        paper.get("tldr"),
        paper.get("summary"),
        paper.get("abstract"),
    ]
    return "\n".join(str(field) for field in fields if field)


def _local_match_score(paper: dict[str, Any], query: str) -> tuple[float, str]:
    q_norm = _normalize(query)
    title_norm = _normalize(paper.get("title"))
    if not q_norm:
        return 0.0, ""
    if title_norm and (q_norm == title_norm or q_norm in title_norm or title_norm in q_norm):
        return 1.0, "本地标题精确/近似匹配"

    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0, ""
    title_tokens = _tokens(paper.get("title"))
    all_tokens = _tokens(_paper_search_text(paper))
    title_overlap = len(q_tokens & title_tokens) / max(len(q_tokens), 1)
    metadata_overlap = len(q_tokens & all_tokens) / max(len(q_tokens), 1)
    title_similarity = SequenceMatcher(None, q_norm, title_norm).ratio() if title_norm else 0.0
    score = max(title_overlap * 0.92, metadata_overlap * 0.72, title_similarity * 0.88)
    reason = "本地标题关键词匹配" if title_overlap >= 0.35 else "本地 metadata/summary 匹配"
    return score, reason


def local_rank_papers(site_dir: Path | str, query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Fast deterministic search over the generated reader metadata.

    This is the source of truth for "is this paper in my database?" queries and
    also acts as a safe fallback when an LLM reranker is slow or returns invalid JSON.
    """

    rows: list[dict[str, Any]] = []
    for paper in _load_papers(site_dir):
        paper_id = str(paper.get("paper_id") or "").strip()
        if not paper_id:
            continue
        score, reason = _local_match_score(paper, query)
        if score <= 0.05:
            continue
        rows.append(
            {
                "paper_id": paper_id,
                "score": max(0.0, min(float(score), 1.0)),
                "reason": reason,
                "suggested_action": "read" if score >= 0.72 else "skim",
                "paper": paper,
            }
        )
    rows.sort(key=lambda item: (item["score"], str(item.get("paper", {}).get("year") or "")), reverse=True)
    return rows[: max(1, int(limit))]


def _candidate_papers(site_dir: Path | str, query: str, limit: int) -> list[dict[str, Any]]:
    matches = [item["paper"] for item in local_rank_papers(site_dir, query, limit=limit) if isinstance(item.get("paper"), dict)]
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


def _should_answer_locally(query: str, local_results: list[dict[str, Any]], payload: dict[str, Any]) -> bool:
    if bool(payload.get("local_only")):
        return True
    if not local_results:
        return False
    top = local_results[0]
    q_word_count = len(_tokens(query))
    # Full-title / paper-existence checks should not wait for an LLM.
    return q_word_count >= 4 and float(top.get("score") or 0) >= 0.90


def _local_response(query: str, provider_id: str, model: str, results: list[dict[str, Any]], *, warning: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "provider_id": provider_id,
        "model": model or "local-index",
        "source": "local-index",
        "results": results,
    }
    if warning:
        payload["warning"] = warning
    return payload


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

    local_results = local_rank_papers(site_dir, query, limit=limit)
    # The reader's public "quick find" UX must never block on an LLM.  It is a
    # database lookup first; callers that explicitly want model reranking can
    # opt in with {"use_llm": true}.
    if not bool(payload.get("use_llm")) or _should_answer_locally(query, local_results, payload):
        return _local_response(query, provider_id, "local-index", local_results[:limit])

    messages = build_ranking_messages(site_dir, query, candidate_limit=candidate_limit)
    kwargs = build_chat_request_kwargs(
        registry,
        provider_id=provider_id,
        model=model,
        messages=messages,
        max_tokens=max(512, min(int(payload.get("max_tokens") or 1200), 2200)),
    )
    base_url = str(kwargs.pop("base_url"))
    api_key = str(kwargs.pop("api_key"))
    selected_model = str(kwargs["model"])
    client = (client_factory or _default_client_factory)(base_url=base_url, api_key=api_key)
    try:
        raw = _response_text(client.chat.completions.create(**kwargs))
        parsed = _extract_json(raw)
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return _local_response(
            query,
            provider_id,
            "local-index",
            local_results[:limit],
            warning=f"LLM rerank failed; showing fast local search results instead: {exc}",
        )
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
