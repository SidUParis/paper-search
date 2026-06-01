"""LLM chat orchestration for the private reader workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from paper_search.reader_context import build_paper_context, related_papers
from paper_search.reader_models import ReaderModelRegistry, build_chat_request_kwargs


SYSTEM_PROMPT = """You are Sidney's private AI paper-reading copilot.
Answer primarily in clear Chinese / 中文 unless the user asks otherwise.
Ground every claim in the provided paper/library context. If the context is insufficient, say so explicitly.
Focus on LLM bias/fairness, BBQ/FrenchBBQ/MultilingualBBQ, evaluation methodology, limitations, and related-work usefulness when relevant.
Do not invent citations, results, or paper details not present in the context.
""".strip()


def _paper_line(paper: dict[str, Any]) -> str:
    title = str(paper.get("title") or "Untitled")
    source = str(paper.get("source_label") or paper.get("venue") or "")
    topic = str(paper.get("topic_slug") or "")
    summary = str(paper.get("summary") or paper.get("abstract") or paper.get("zh_brief") or "")
    bits = [f"- {title}"]
    meta = ", ".join(item for item in [source, topic] if item)
    if meta:
        bits.append(f"({meta})")
    if summary:
        bits.append(f": {summary}")
    return " ".join(bits)


def build_chat_messages(
    site_dir: Path | str,
    question: str,
    paper_key: str | None = None,
    mode: str = "balanced",
    allowed_roots: list[Path] | None = None,
    max_fulltext_chars: int = 24000,
) -> list[dict[str, str]]:
    """Build OpenAI-compatible chat messages for paper or library QA."""

    question = question.strip()
    if not question:
        raise ValueError("question is required")

    if paper_key:
        context = build_paper_context(
            site_dir,
            paper_key,
            mode=mode,
            allowed_roots=allowed_roots,
            max_fulltext_chars=max_fulltext_chars,
        )
        user_content = (
            "Use the following grounded paper context to answer the user's question.\n\n"
            f"[Paper context]\n{context.text}\n\n"
            f"[User question]\n{question}"
        )
    else:
        matches = related_papers(site_dir, question, top_k=8)
        if matches:
            library_context = "\n".join(_paper_line(paper) for paper in matches)
        else:
            library_context = "No related papers were found in the current generated reader index."
        user_content = (
            "Use the related papers from the user's local library to answer.\n\n"
            f"[Related library papers]\n{library_context}\n\n"
            f"[User question]\n{question}"
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _default_client_factory(**kwargs: Any) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency exists in normal installs
        raise RuntimeError("openai package is required for reader chat") from exc
    return OpenAI(**kwargs)


def _extract_answer(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError("unexpected chat completion response shape") from exc
    if isinstance(content, list):
        # Some providers return a structured content list; keep text-like pieces.
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text_parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                text_parts.append(str(item))
        content = "".join(text_parts)
    answer = str(content or "").strip()
    if not answer:
        raise RuntimeError("model returned an empty answer")
    return answer


def generate_chat_response(
    registry: ReaderModelRegistry,
    site_dir: Path | str,
    payload: dict[str, Any],
    allowed_roots: list[Path] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Generate a grounded answer through a configured OpenAI-compatible provider."""

    provider_id = str(payload.get("provider_id") or "deepseek").strip()
    model = str(payload.get("model") or "").strip()
    question = str(payload.get("question") or payload.get("message") or "").strip()
    paper_key_raw = payload.get("paper_key") or payload.get("paper_id") or payload.get("slug")
    paper_key = str(paper_key_raw).strip() if paper_key_raw else None
    mode = str(payload.get("mode") or ("balanced" if paper_key else "library")).strip()
    max_tokens = int(payload.get("max_tokens") or 1200)
    max_fulltext_chars = int(payload.get("max_fulltext_chars") or 24000)

    messages = build_chat_messages(
        site_dir,
        question=question,
        paper_key=paper_key,
        mode=mode,
        allowed_roots=allowed_roots,
        max_fulltext_chars=max_fulltext_chars,
    )
    kwargs = build_chat_request_kwargs(
        registry,
        provider_id=provider_id,
        model=model,
        messages=messages,
        max_tokens=max(128, min(max_tokens, 4000)),
    )
    base_url = str(kwargs.pop("base_url"))
    api_key = str(kwargs.pop("api_key"))
    selected_model = str(kwargs["model"])
    client = (client_factory or _default_client_factory)(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(**kwargs)
    answer = _extract_answer(response)
    return {
        "answer": answer,
        "provider_id": provider_id,
        "model": selected_model,
        "paper_key": paper_key,
        "mode": mode,
    }
