"""Generate project-specific reading queues from extracted review rows."""

from __future__ import annotations

from typing import Any


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default



def _row_extraction(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("extraction") or {}



def _score_multilingual_bias_row(row: dict[str, Any]) -> tuple[int, list[str]]:
    extraction = _row_extraction(row)
    score = 0
    reasons: list[str] = []
    score += round(float(row.get("screening_confidence") or 0) * 10)
    if extraction.get("relevance_to_multilingual_unified_bbq") == "high":
        score += 35
        reasons.append("high relevance to unified multilingual BBQ")
    if extraction.get("relevance_to_frenchbbq") == "high":
        score += 20
        reasons.append("direct relevance to FrenchBBQ")
    if extraction.get("benchmark_role") == "introduces_benchmark":
        score += 20
        reasons.append("introduces a benchmark")
    if extraction.get("native_authored_data"):
        score += 15
        reasons.append("includes native-authored data")
    if extraction.get("cross_lingual_comparison_present"):
        score += 10
        reasons.append("explicit cross-lingual comparison")
    if extraction.get("human_evaluation_used"):
        score += 8
        reasons.append("uses human evaluation")
    if extraction.get("translation_based"):
        score += 5
        reasons.append("translation-based benchmark construction evidence")
    if extraction.get("benchmark_name"):
        score += 5
    return score, reasons



def _score_conv_summarization_row(row: dict[str, Any]) -> tuple[int, list[str]]:
    extraction = _row_extraction(row)
    score = 0
    reasons: list[str] = []
    score += round(float(row.get("screening_confidence") or 0) * 10)
    if extraction.get("evaluation_focus") == "faithfulness":
        score += 25
        reasons.append("faithfulness-focused evaluation")
    if extraction.get("streaming_or_real_time"):
        score += 18
        reasons.append("real-time or streaming setting")
    if extraction.get("multilingual_or_crosslingual"):
        score += 15
        reasons.append("multilingual or cross-lingual")
    if extraction.get("input_modality") == "speech_or_transcript":
        score += 12
        reasons.append("speech/transcript input")
    if extraction.get("benchmark_name"):
        score += 10
        reasons.append("benchmark or dataset anchor")
    if extraction.get("dialogue_domain") not in (None, "", "other"):
        score += 5
        reasons.append(f"domain={extraction.get('dialogue_domain')}")
    return score, reasons



def _score_sycophancy_row(row: dict[str, Any]) -> tuple[int, list[str]]:
    extraction = _row_extraction(row)
    score = 0
    reasons: list[str] = []
    score += round(float(row.get("screening_confidence") or 0) * 10)
    if extraction.get("evaluation_target") in {"measurement", "mitigation"}:
        score += 22
        reasons.append(f"evaluation_target={extraction.get('evaluation_target')}")
    if extraction.get("benchmark_or_dataset"):
        score += 18
        reasons.append("benchmark/dataset-centered")
    if extraction.get("feedback_loop_involved"):
        score += 15
        reasons.append("connected to RLHF / feedback loops")
    if extraction.get("user_opinion_conditioned"):
        score += 12
        reasons.append("explicit user-opinion conditioning")
    if extraction.get("setup_type") not in (None, "", "other"):
        score += 8
        reasons.append(f"setup={extraction.get('setup_type')}")
    if extraction.get("llm_used"):
        score += 5
    return score, reasons



def score_queue_item(project, row: dict[str, Any]) -> dict[str, Any]:
    pid = project.review_project_id
    if pid == "multilingual-bias-benchmark-landscape":
        score, reasons = _score_multilingual_bias_row(row)
    elif pid == "conversational-summarization-landscape":
        score, reasons = _score_conv_summarization_row(row)
    elif pid == "sycophancy-evaluation-landscape":
        score, reasons = _score_sycophancy_row(row)
    else:
        score = round(float(row.get("screening_confidence") or 0) * 10)
        reasons = []
    if score >= 55:
        priority_bucket = "read_today"
    elif score >= 30:
        priority_bucket = "this_week"
    else:
        priority_bucket = "backlog"
    return {"score": score, "priority_bucket": priority_bucket, "reasons": reasons}



def generate_reading_queue(project, rows: list[dict[str, Any]], top_today: int = 3, top_week: int = 10) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in rows:
        meta = score_queue_item(project, row)
        item = dict(row)
        item.update(meta)
        ranked.append(item)
    ranked.sort(
        key=lambda row: (
            -_safe_int(row.get("score")),
            -_safe_int(row.get("year"), 0),
            str(row.get("title", "")).lower(),
        )
    )
    today_used = 0
    week_used = 0
    for item in ranked:
        bucket = item.get("priority_bucket")
        if bucket == "read_today":
            if today_used >= top_today:
                item["priority_bucket"] = "this_week"
            else:
                today_used += 1
        if item.get("priority_bucket") == "this_week":
            if week_used >= top_week:
                item["priority_bucket"] = "backlog"
            else:
                week_used += 1
    return ranked



def render_reading_queue_markdown(project, ranked_rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# Reading Queue — {project.review_project_name}",
        "",
        "## Read today",
    ]
    today = [row for row in ranked_rows if row.get("priority_bucket") == "read_today"]
    week = [row for row in ranked_rows if row.get("priority_bucket") == "this_week"]
    backlog = [row for row in ranked_rows if row.get("priority_bucket") == "backlog"]
    for bucket_rows, empty_text in [(today, "- None yet"), (week, "- None yet"), (backlog[:15], "- None")]:
        if bucket_rows is today:
            pass
    if today:
        for row in today:
            lines.extend(_render_queue_item(row))
    else:
        lines.append("- None yet")
    lines += ["", "## This week"]
    if week:
        for row in week:
            lines.extend(_render_queue_item(row))
    else:
        lines.append("- None yet")
    lines += ["", "## Backlog"]
    if backlog:
        for row in backlog[:15]:
            lines.extend(_render_queue_item(row))
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)



def _render_queue_item(row: dict[str, Any]) -> list[str]:
    title = str(row.get("title", "Untitled"))
    score = row.get("score")
    year = row.get("year")
    extraction = _row_extraction(row)
    bits = [f"- **{title}**"]
    meta = []
    if year:
        meta.append(str(year))
    if extraction.get("paper_type"):
        meta.append(f"paper_type={extraction.get('paper_type')}")
    if extraction.get("benchmark_name"):
        meta.append(f"benchmark={extraction.get('benchmark_name')}")
    if score is not None:
        meta.append(f"score={score}")
    if meta:
        bits.append(f"  - {' | '.join(meta)}")
    reasons = row.get("reasons") or []
    if reasons:
        bits.append(f"  - Why now: {'; '.join(reasons[:3])}")
    return bits
