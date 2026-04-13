"""Generate short operational digests from extracted review rows."""

from __future__ import annotations

from collections import Counter
from typing import Any

from paper_search.review_gap_summary import aggregate_review_signals
from paper_search.review_queue import generate_reading_queue



def _top_titles(rows: list[dict[str, Any]], limit: int = 5) -> list[str]:
    return [str(row.get("title", "")).strip() for row in rows[:limit] if str(row.get("title", "")).strip()]



def _field_counter(rows: list[dict[str, Any]], field: str) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        extraction = row.get("extraction") or {}
        value = extraction.get(field)
        if value in (None, "", []):
            continue
        counter[str(value)] += 1
    return counter



def _watchlist_notes(project_id: str, rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if project_id == "multilingual-bias-benchmark-landscape":
        counter = _field_counter(rows, "benchmark_role")
        if counter.get("introduces_benchmark", 0):
            lines.append("- Keep watching newly introduced benchmarks that could transfer into FrenchBBQ / unified multilingual BBQ design.")
    elif project_id == "conversational-summarization-landscape":
        counter = _field_counter(rows, "evaluation_focus")
        if counter.get("faithfulness", 0):
            lines.append("- Faithfulness-focused papers should be tracked continuously because they are still rarer than summary-quality work.")
    elif project_id == "sycophancy-evaluation-landscape":
        counter = _field_counter(rows, "evaluation_target")
        if counter.get("mitigation", 0) < counter.get("measurement", 0):
            lines.append("- Mitigation papers remain relatively scarce, so new ones deserve immediate attention.")
    return lines



def generate_review_digest(project, rows: list[dict[str, Any]], synthesis_text: str = "", idea_slate_text: str = "", period: str = "weekly", window_label: str = "") -> str:
    signals = aggregate_review_signals(project, rows)
    ranked = generate_reading_queue(project, rows, top_today=3, top_week=8)
    read_today = [row for row in ranked if row.get("priority_bucket") == "read_today"]
    this_week = [row for row in ranked if row.get("priority_bucket") == "this_week"]
    gap_counts = signals.get("gap_counts") or {}
    top_gaps = sorted(gap_counts.items(), key=lambda item: (-item[1], item[0]))[:5]

    lines = [
        f"# {period.title()} Digest — {project.review_project_name}",
        "",
        "## Window",
        f"- {window_label or 'Current local extracted review cache'}",
        f"- Included / extracted papers considered: {len(rows)}",
        "",
        "## What landed this period",
    ]
    titles = _top_titles(rows, 5)
    if titles:
        lines.extend(f"- {title}" for title in titles)
    else:
        lines.append("- No extracted papers yet.")

    lines += ["", "## Main topic shifts / recurring patterns"]
    for field, counts in (signals.get("signal_counts") or {}).items():
        if not counts:
            continue
        best = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]
        lines.append(f"- {field}: " + ", ".join(f"{name} ({count})" for name, count in best))

    lines += ["", "## Important papers to read first"]
    if read_today:
        for row in read_today:
            reasons = row.get("reasons") or []
            lines.append(f"- {row.get('title', '')} — {'; '.join(reasons[:2]) if reasons else 'top queue priority'}")
    else:
        lines.append("- No read-today items yet.")

    lines += ["", "## Emerging gaps or opportunities"]
    if top_gaps:
        for name, count in top_gaps:
            lines.append(f"- {name} ({count})")
    else:
        lines.append("- No recurring gap tags yet; rely on topic signal imbalances instead.")

    lines += ["", "## Watchlist next week"]
    watchlist = _watchlist_notes(project.review_project_id, rows)
    if this_week:
        lines.extend(f"- {row.get('title', '')}" for row in this_week[:5])
    if watchlist:
        lines.extend(watchlist)
    if not this_week and not watchlist:
        lines.append("- No watchlist items yet.")

    if synthesis_text.strip():
        first_line = next((line.strip() for line in synthesis_text.splitlines() if line.strip() and not line.startswith('#')), "")
        if first_line:
            lines += ["", "## Synthesis hook", f"- {first_line}"]
    if idea_slate_text.strip():
        idea_line = next((line.strip() for line in idea_slate_text.splitlines() if line.strip().startswith('- Core idea:')), "")
        if idea_line:
            lines += ["", "## Idea hook", idea_line]
    lines.append("")
    return "\n".join(lines)
