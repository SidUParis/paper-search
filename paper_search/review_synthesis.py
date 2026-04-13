"""Review-project synthesis helpers."""

from __future__ import annotations

import json
import time
from collections import Counter

from paper_search.summarizer import get_llm_client


_PROJECT_TEMPLATES = {
    "multilingual-bias-benchmark-landscape": {
        "sections": [
            "## Included papers",
            "## Benchmark families and language coverage",
            "## Data construction patterns",
            "## Evaluation protocols and aggregation choices",
            "## Main gaps for multilingual bias benchmark design",
            "## Research ideas for FrenchBBQ / unified multilingual BBQ",
            "## Relevance to thesis",
        ],
        "instruction": (
            "Focus on benchmark families, language coverage, translation-based vs native-authored construction, "
            "evaluation protocols, metric aggregation, and concrete implications for FrenchBBQ and a unified multilingual BBQ. "
            "In the research-ideas section, propose only ideas grounded in the extracted evidence."
        ),
    },
    "conversational-summarization-landscape": {
        "sections": [
            "## Included papers",
            "## Dataset and benchmark landscape",
            "## Dialogue domains and input modalities",
            "## Evaluation patterns beyond ROUGE",
            "## Main gaps for conversational summarization research",
            "## Research ideas worth testing",
            "## Relevance to thesis",
        ],
        "instruction": (
            "Emphasize dialogue domains, meeting/chat/task settings, speech vs text vs multimodal inputs, "
            "faithfulness and human evaluation, and where the literature leaves room for strong new work."
        ),
    },
    "sycophancy-evaluation-landscape": {
        "sections": [
            "## Included papers",
            "## How sycophancy is operationalized",
            "## Benchmarks, elicitation setups, and evaluation targets",
            "## Relationship to RLHF, alignment, and preference optimization",
            "## Main gaps for sycophancy research",
            "## Research ideas worth testing",
            "## Relevance to thesis",
        ],
        "instruction": (
            "Highlight operational definitions of sycophancy, elicitation setups, measurement vs mitigation, "
            "and the boundary with alignment faking or generic RLHF effects."
        ),
    },
}


def _template_for_project(project) -> dict[str, object]:
    return _PROJECT_TEMPLATES.get(
        project.review_project_id,
        {
            "sections": [
                "## Included papers",
                "## Main patterns",
                "## Gaps",
                "## Research ideas worth testing",
                "## Relevance to thesis",
            ],
            "instruction": "Summarize cross-paper patterns, gaps, and a few evidence-grounded research ideas.",
        },
    )


def _render_template_header(project) -> list[str]:
    template = _template_for_project(project)
    lines = ["# Review Synthesis", "", f"**Project:** {project.review_project_name}", f"**Objective:** {project.objective}", ""]
    lines.append("## Research questions")
    lines.extend(f"- {q}" for q in project.research_questions)
    lines.append("")
    lines.extend(template["sections"])
    return lines


def _fallback_markdown(project, rows: list[dict]) -> str:
    included_titles = [row.get("title", "") for row in rows]
    benchmark_counter = Counter()
    scope_counter = Counter()
    paper_type_counter = Counter()
    gap_counter = Counter()
    for row in rows:
        extraction = row.get("extraction") or {}
        if extraction.get("benchmark_name"):
            benchmark_counter[str(extraction["benchmark_name"])] += 1
        if extraction.get("language_scope"):
            scope_counter[str(extraction["language_scope"])] += 1
        if extraction.get("paper_type"):
            paper_type_counter[str(extraction["paper_type"])] += 1
        for gap in extraction.get("review_gap_tags") or []:
            gap_counter[str(gap)] += 1

    template = _template_for_project(project)
    sections = list(template["sections"])
    lines = ["# Review Synthesis", "", f"**Project:** {project.review_project_name}", f"**Objective:** {project.objective}", ""]
    lines.append("## Research questions")
    lines.extend(f"- {q}" for q in project.research_questions)
    lines.append("")

    if sections:
        lines.append(sections[0])
        for title in included_titles[:50]:
            lines.append(f"- {title}")
        if not included_titles:
            lines.append("- None yet")

    remaining = sections[1:]
    for heading in remaining:
        lines += ["", heading]
        lowered = heading.lower()
        if "benchmark" in lowered or "dataset" in lowered:
            if benchmark_counter:
                lines.append(f"- Benchmarks/datasets surfaced: {dict(benchmark_counter)}")
            else:
                lines.append("- No benchmark or dataset names were extracted yet.")
        elif "language" in lowered or "coverage" in lowered or "construction" in lowered:
            if scope_counter:
                lines.append(f"- Language-related extracted signals: {dict(scope_counter)}")
            else:
                lines.append("- No language-scope summary was extracted yet.")
        elif "operationalized" in lowered or "elicitation" in lowered or "evaluation targets" in lowered:
            if paper_type_counter:
                lines.append(f"- Paper types / study modes: {dict(paper_type_counter)}")
            else:
                lines.append("- No structured operationalization summary available yet.")
        elif "gaps" in lowered:
            if gap_counter:
                lines.append(f"- Frequent gap tags: {dict(gap_counter)}")
            else:
                lines.append("- No explicit gap tags were extracted yet.")
        elif "idea" in lowered:
            lines.append("- Candidate idea 1: test an under-covered setting highlighted by the extracted gaps.")
            lines.append("- Candidate idea 2: build a cleaner benchmark or evaluation split around the dominant open problem in this topic.")
            lines.append("- Candidate idea 3: compare strong baselines on the most under-analyzed dimension surfaced above.")
        elif "relevance to thesis" in lowered:
            lines.append("- Use this synthesis as a prioritization memo for which subproblems deserve deeper reading and experimentation next.")
        else:
            lines.append("- No structured summary available yet for this section.")
    return "\n".join(lines) + "\n"


def _synthesis_messages(project, rows: list[dict], model: str) -> list[dict[str, str]]:
    payload = [
        {
            "title": row.get("title", ""),
            "screening_rationale": row.get("screening_rationale", ""),
            "extraction": row.get("extraction") or {},
        }
        for row in rows
    ]
    template = _template_for_project(project)
    section_text = "\n".join(template["sections"])
    prompt = f"""
You are synthesizing a structured literature review.

Review project: {project.review_project_name}
Objective: {project.objective}
Research questions:
""".strip()
    prompt += "\n" + "\n".join(f"- {q}" for q in project.research_questions)
    prompt += (
        "\n\nUse the extracted records below as the only evidence source. "
        f"{template['instruction']}\n"
        "Return markdown using exactly this structure:\n"
        "# Review Synthesis\n"
        "## Research questions\n"
        f"{section_text}\n\n"
        "Requirements:\n"
        "- Be concrete and cross-paper, not paper-by-paper only.\n"
        "- Mention uncertainty when evidence is sparse.\n"
        "- In the research-ideas section, propose 3-5 ideas that are feasible and explicitly grounded in the extracted evidence.\n"
        "- Each idea should mention why it is promising and what gap it targets.\n\n"
        f"Extracted records:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    if "gemma" in model.lower():
        return [{"role": "user", "content": prompt}]
    return [
        {"role": "system", "content": "You are a careful research synthesis assistant. Use only the provided extracted records."},
        {"role": "user", "content": prompt},
    ]


def synthesize_review(project, rows: list[dict], max_retries: int = 3) -> str:
    if not rows:
        return _fallback_markdown(project, rows)

    try:
        client, model = get_llm_client()
    except Exception:
        return _fallback_markdown(project, rows)
    messages = _synthesis_messages(project, rows, model)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1400,
                temperature=0.1,
            )
            text = (response.choices[0].message.content or "").strip() if response.choices else ""
            if text:
                return text
            raise ValueError("empty synthesis output")
        except Exception as e:
            last_error = e
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
                continue
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return _fallback_markdown(project, rows)
    return _fallback_markdown(project, rows)
