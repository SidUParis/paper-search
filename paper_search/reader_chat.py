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
    mode: str = "full_pdf",
    allowed_roots: list[Path] | None = None,
    max_fulltext_chars: int = 200000,
    reading_note: str | None = None,
    selected_visual: dict[str, Any] | None = None,
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
        extra_parts: list[str] = []
        if reading_note and reading_note.strip():
            extra_parts.append(f"[Reader note]\n{reading_note.strip()}")
        if selected_visual:
            title = str(selected_visual.get("title") or "Selected visual").strip()
            page = str(selected_visual.get("page") or "?").strip()
            caption = str(selected_visual.get("caption") or "").strip()
            kind = str(selected_visual.get("kind") or "visual").strip()
            visual_text = f"{title} ({kind}, page {page})"
            if caption:
                visual_text += f"\nCaption: {caption}"
            preview = selected_visual.get("preview")
            if isinstance(preview, list) and preview:
                rows = []
                for row in preview[:4]:
                    if isinstance(row, list):
                        cells = [str(cell).strip() for cell in row[:5] if str(cell).strip()]
                        if cells:
                            rows.append(" | ".join(cells))
                if rows:
                    visual_text += "\nTable preview: " + " / ".join(rows)
            extra_parts.append(f"[Selected visual]\n{visual_text}")
        extra_context = "\n\n" + "\n\n".join(extra_parts) if extra_parts else ""
        user_content = (
            "Use the following grounded paper context to answer the user's question.\n\n"
            f"[Paper context]\n{context.text}{extra_context}\n\n"
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
        message = response.choices[0].message
        content = message.content
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
    if answer:
        return answer

    # DeepSeek reasoning models can spend the whole token budget in
    # reasoning_content and leave message.content empty. Returning a rough answer
    # is better UX than surfacing a dead-end browser error; the frontend also now
    # asks for a larger token budget to make this rare.
    reasoning = str(getattr(message, "reasoning_content", "") or "").strip()
    if reasoning:
        return "模型只返回了推理草稿、没有生成最终答复；下面是可读版草稿：\n\n" + reasoning
    raise RuntimeError("model returned an empty answer")


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
    mode = str(payload.get("mode") or ("full_pdf" if paper_key else "library")).strip()
    max_tokens = int(payload.get("max_tokens") or (3200 if paper_key else 4000))
    max_fulltext_chars = int(payload.get("max_fulltext_chars") or 200000)
    reading_note = str(payload.get("reading_note") or "").strip() or None
    selected_visual_raw = payload.get("selected_visual")
    selected_visual = selected_visual_raw if isinstance(selected_visual_raw, dict) else None

    messages = build_chat_messages(
        site_dir,
        question=question,
        paper_key=paper_key,
        mode=mode,
        allowed_roots=allowed_roots,
        max_fulltext_chars=max_fulltext_chars,
        reading_note=reading_note,
        selected_visual=selected_visual,
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
