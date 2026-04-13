"""Generate research-idea slates from review outputs."""

from __future__ import annotations

import json
import time
from collections import Counter

from paper_search.summarizer import get_llm_client


_PROJECT_IDEA_PROMPTS = {
    "multilingual-bias-benchmark-landscape": "Focus on benchmark design ideas for FrenchBBQ and a unified multilingual BBQ: language coverage, native-vs-translation construction, metric aggregation, and culturally grounded evaluation.",
    "conversational-summarization-landscape": "Focus on feasible conversational summarization ideas: under-covered dialogue domains, multimodal or spoken settings, faithfulness evaluation, and realistic benchmark design.",
    "sycophancy-evaluation-landscape": "Focus on feasible sycophancy ideas: clearer operationalization, better elicitation benchmarks, measurement-vs-mitigation protocols, and RLHF/alignment-faking disentanglement.",
}


def _idea_prompt_for_project(project) -> str:
    return _PROJECT_IDEA_PROMPTS.get(project.review_project_id, "Focus on feasible, evidence-grounded research ideas derived from the extracted records.")


def _fallback_idea_slate(project, rows: list[dict], gap_summary_text: str = "") -> str:
    benchmark_counter = Counter()
    gap_counter = Counter()
    paper_type_counter = Counter()
    for row in rows:
        extraction = row.get("extraction") or {}
        if extraction.get("benchmark_name"):
            benchmark_counter[str(extraction.get("benchmark_name"))] += 1
        if extraction.get("paper_type"):
            paper_type_counter[str(extraction.get("paper_type"))] += 1
        for gap in extraction.get("review_gap_tags") or []:
            gap_counter[str(gap)] += 1

    top_benchmarks = [name for name, _ in benchmark_counter.most_common(3)]
    top_gaps = [name for name, _ in gap_counter.most_common(4)]
    lines = [
        f"# Idea Slate — {project.review_project_name}",
        "",
        "## Candidate ideas",
        "",
    ]
    for idx in range(1, 4):
        benchmark_text = ", ".join(top_benchmarks) if top_benchmarks else "the core extracted benchmarks"
        gap_text = ", ".join(top_gaps[:2]) if top_gaps else "the main recurring open gaps"
        lines += [
            f"### Idea {idx}",
            f"- Core idea: Build a focused study around {gap_text} using {benchmark_text} as anchor evidence.",
            f"- Why promising: the extracted review records repeatedly point to {gap_text or 'open design gaps'}.",
            "- Minimal executable version: run a small controlled benchmark or comparison on a single sharply defined subproblem.",
            "- Risk level: medium.",
            "- Expected contribution: clearer benchmarking or evaluation evidence for this topic.",
            "",
        ]
    lines += [
        "## Prioritization notes",
        f"- Dominant paper types: {dict(paper_type_counter) if paper_type_counter else 'unknown'}",
        f"- Dominant gap tags: {dict(gap_counter) if gap_counter else 'none extracted yet'}",
    ]
    if gap_summary_text.strip():
        lines += ["", "## Gap-summary hook", gap_summary_text.strip().splitlines()[0] if gap_summary_text.strip().splitlines() else ""]
    return "\n".join(lines).strip() + "\n"


def _idea_messages(project, rows: list[dict], synthesis_text: str, gap_summary_text: str, model: str) -> list[dict[str, str]]:
    payload = [
        {
            "title": row.get("title", ""),
            "screening_rationale": row.get("screening_rationale", ""),
            "extraction": row.get("extraction") or {},
        }
        for row in rows
    ]
    prompt = f"""
You are generating a research idea slate from a structured literature review.

Review project: {project.review_project_name}
Objective: {project.objective}
Research questions:
""".strip()
    prompt += "\n" + "\n".join(f"- {q}" for q in project.research_questions)
    prompt += (
        "\n\nTask instructions:\n"
        f"- {_idea_prompt_for_project(project)}\n"
        "- Use only the extracted review records and synthesis below.\n"
        "- Return markdown with exactly these sections:\n"
        "# Idea Slate\n"
        "## Candidate ideas\n"
        "### Idea 1\n"
        "### Idea 2\n"
        "### Idea 3\n"
        "## Prioritization notes\n\n"
        "For each idea include bullet points for:\n"
        "- Core idea\n"
        "- Why promising\n"
        "- Minimal executable version\n"
        "- Risk level\n"
        "- Expected contribution\n"
        "Ideas must be feasible and evidence-grounded, not generic slogans.\n\n"
        f"Synthesis:\n{synthesis_text}\n\n"
        f"Gap summary:\n{gap_summary_text}\n\n"
        f"Extracted records:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    if "gemma" in model.lower():
        return [{"role": "user", "content": prompt}]
    return [
        {"role": "system", "content": "You are a careful research-idea assistant. Use only the provided evidence."},
        {"role": "user", "content": prompt},
    ]


def generate_idea_slate(project, rows: list[dict], synthesis_text: str, gap_summary_text: str = "", max_retries: int = 3) -> str:
    if not rows:
        return _fallback_idea_slate(project, rows, gap_summary_text=gap_summary_text)

    try:
        client, model = get_llm_client()
    except Exception:
        return _fallback_idea_slate(project, rows, gap_summary_text=gap_summary_text)
    messages = _idea_messages(project, rows, synthesis_text, gap_summary_text, model)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1200,
                temperature=0.2,
            )
            text = (response.choices[0].message.content or "").strip() if response.choices else ""
            if text:
                return text
            raise ValueError("empty idea slate output")
        except Exception as e:
            last_error = e
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
                continue
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return _fallback_idea_slate(project, rows, gap_summary_text=gap_summary_text)
    return _fallback_idea_slate(project, rows, gap_summary_text=gap_summary_text)
