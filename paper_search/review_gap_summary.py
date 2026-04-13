"""Aggregate project-level signals and render research gap summaries."""

from __future__ import annotations

from collections import Counter
from typing import Any


_PROJECT_SIGNAL_FIELDS: dict[str, list[str]] = {
    "multilingual-bias-benchmark-landscape": [
        "paper_type",
        "benchmark_role",
        "bias_type",
        "language_scope",
        "translation_based",
        "native_authored_data",
        "human_evaluation_used",
        "cross_lingual_comparison_present",
    ],
    "conversational-summarization-landscape": [
        "paper_type",
        "dialogue_domain",
        "input_modality",
        "evaluation_focus",
        "llm_used",
        "multilingual_or_crosslingual",
        "streaming_or_real_time",
    ],
    "sycophancy-evaluation-landscape": [
        "paper_type",
        "setup_type",
        "evaluation_target",
        "user_opinion_conditioned",
        "feedback_loop_involved",
        "llm_used",
        "benchmark_or_dataset",
    ],
}


def _counter_for(rows: list[dict[str, Any]], field: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        extraction = row.get("extraction") or {}
        value = extraction.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            for item in value:
                if item not in (None, "", []):
                    counter[str(item)] += 1
        else:
            counter[str(value)] += 1
    return counter



def _gap_counter(rows: list[dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        extraction = row.get("extraction") or {}
        for item in extraction.get("review_gap_tags") or []:
            if item:
                counter[str(item)] += 1
    return counter



def _top_priority_rows(project, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from paper_search.review_queue import generate_reading_queue

    ranked = generate_reading_queue(project, rows, top_today=5, top_week=8)
    return [row for row in ranked if row.get("priority_bucket") in {"read_today", "this_week"}][:8]



def aggregate_review_signals(project, rows: list[dict[str, Any]]) -> dict[str, Any]:
    signal_fields = _PROJECT_SIGNAL_FIELDS.get(project.review_project_id, ["paper_type"])
    signals = {
        "review_project_id": project.review_project_id,
        "project_name": project.review_project_name,
        "paper_count": len(rows),
        "signal_counts": {field: dict(_counter_for(rows, field)) for field in signal_fields},
        "gap_counts": dict(_gap_counter(rows)),
        "priority_rows": [
            {
                "title": row.get("title", ""),
                "paper_id": row.get("paper_id", ""),
                "score": row.get("score"),
                "year": row.get("year"),
                "reasons": row.get("reasons") or [],
                "extraction": row.get("extraction") or {},
            }
            for row in _top_priority_rows(project, rows)
        ],
    }
    return signals



def _undercovered_lines(project_id: str, signal_counts: dict[str, dict[str, int]]) -> list[str]:
    lines: list[str] = []
    if project_id == "multilingual-bias-benchmark-landscape":
        native = signal_counts.get("native_authored_data", {})
        human = signal_counts.get("human_evaluation_used", {})
        if native.get("True", 0) == 0:
            lines.append("- Native-authored benchmark construction appears absent or extremely rare.")
        if human.get("True", 0) < human.get("False", 0):
            lines.append("- Human evaluation is still underused relative to automatic evaluation.")
    elif project_id == "conversational-summarization-landscape":
        focus = signal_counts.get("evaluation_focus", {})
        if focus.get("faithfulness", 0) < max(1, focus.get("summary_quality", 0) // 2):
            lines.append("- Faithfulness-focused conversational summarization papers remain under-covered relative to generic summary-quality evaluation.")
        streaming = signal_counts.get("streaming_or_real_time", {})
        if streaming.get("True", 0) == 0:
            lines.append("- Real-time / streaming conversational summarization remains sparse.")
    elif project_id == "sycophancy-evaluation-landscape":
        target = signal_counts.get("evaluation_target", {})
        if target.get("mitigation", 0) < max(1, target.get("measurement", 0) // 2):
            lines.append("- Mitigation work lags behind measurement-focused sycophancy evaluation.")
        setup = signal_counts.get("setup_type", {})
        if setup.get("roleplay", 0) == 0:
            lines.append("- Roleplay/persona elicitation appears weakly represented.")
    return lines



def render_gap_summary_markdown(project, signals: dict[str, Any]) -> str:
    signal_counts = signals.get("signal_counts") or {}
    gap_counts = signals.get("gap_counts") or {}
    priority_rows = signals.get("priority_rows") or []
    lines = [
        f"# Research Gap Summary — {project.review_project_name}",
        "",
        "## Topic-level signals",
        f"- Included / extracted papers: {signals.get('paper_count', 0)}",
    ]
    for field, counts in signal_counts.items():
        if not counts:
            continue
        sorted_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        bits = ", ".join(f"{name}: {count}" for name, count in sorted_counts[:5])
        lines.append(f"- {field}: {bits}")
    lines += ["", "## Recurring gaps"]
    if gap_counts:
        for name, count in sorted(gap_counts.items(), key=lambda item: (-item[1], item[0]))[:8]:
            lines.append(f"- {name} ({count})")
    else:
        lines.append("- No explicit review_gap_tags surfaced yet.")
    lines += ["", "## Under-covered combinations"]
    undercovered = _undercovered_lines(project.review_project_id, signal_counts)
    if undercovered:
        lines.extend(undercovered)
    else:
        lines.append("- No obvious under-covered combination detected from current structured counts.")
    lines += ["", "## High-priority papers for follow-up"]
    if priority_rows:
        for row in priority_rows[:6]:
            extraction = row.get("extraction") or {}
            bits = []
            if extraction.get("benchmark_name"):
                bits.append(f"benchmark={extraction.get('benchmark_name')}")
            if extraction.get("paper_type"):
                bits.append(f"paper_type={extraction.get('paper_type')}")
            lines.append(f"- {row.get('title', '')} — {'; '.join(bits) if bits else 'high queue priority'}")
    else:
        lines.append("- No priority papers yet.")
    lines += ["", "## Next-step ideas for PhD workflow"]
    if project.review_project_id == "multilingual-bias-benchmark-landscape":
        lines += [
            "- Audit which multilingual benchmark papers rely on translation-based construction versus native-authored data.",
            "- Prioritize papers with human evaluation and cross-lingual comparison for benchmark design transfer into unified multilingual BBQ.",
        ]
    elif project.review_project_id == "conversational-summarization-landscape":
        lines += [
            "- Build a focused reading set around faithfulness and spoken/transcript settings.",
            "- Compare benchmark-heavy papers with method-heavy papers to see where evaluation mismatches persist.",
        ]
    elif project.review_project_id == "sycophancy-evaluation-landscape":
        lines += [
            "- Separate measurement-heavy papers from mitigation-heavy papers and inspect where RLHF feedback loops dominate the story.",
            "- Prioritize benchmark/dataset papers that could anchor a clearer sycophancy evaluation protocol.",
        ]
    lines.append("")
    return "\n".join(lines)
