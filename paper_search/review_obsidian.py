"""Sync review outputs into the local Obsidian vault."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian Vault"
START = "<!-- REVIEW_SYNC_START -->"
END = "<!-- REVIEW_SYNC_END -->"


def get_obsidian_vault() -> Path:
    raw = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(raw).expanduser() if raw else DEFAULT_VAULT


def _review_note_path(project) -> Path:
    return get_obsidian_vault() / "reviews" / f"{project.review_project_id}.md"


def _review_map_path(project) -> Path:
    return get_obsidian_vault() / "reviews" / f"{project.review_project_id}-map.md"


def _paper_note_path(paper_id: str) -> Path:
    return get_obsidian_vault() / "papers" / f"{paper_id}.md"


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---\n"):
        marker = "\n---\n"
        end = text.find(marker, 4)
        if end != -1:
            frontmatter_text = text[4:end]
            body = text[end + len(marker):]
            return dict(yaml.safe_load(frontmatter_text) or {}), body
    return {}, text


def _dump_frontmatter(data: dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip() + "\n---\n"


def _normalize_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return [str(value)]


def _title_from_body(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _paper_note_stub(project, record: dict[str, Any], extraction: dict[str, Any]) -> str:
    title = str(record.get("title", "Untitled")).strip()
    paper_id = str(record.get("paper_id", "")).strip()
    today = datetime.now().strftime("%Y-%m-%d")
    summary = str(record.get("summary", "")).strip()
    rationale = str(record.get("screening_rationale", "")).strip()
    frontmatter = {
        "title": title,
        "created": today,
        "updated": today,
        "type": "paper",
        "tags": ["paper", project.source_topic_slug, "review-aligned"],
        "notion_url": str(record.get("notion_url") or ""),
        "status": "active",
        "aliases": [title],
        "area": project.source_topic_slug,
        "project": "thesis",
        "language_scope": _normalize_list(extraction.get("language_scope")),
        "priority": "high" if extraction.get("relevance_to_multilingual_unified_bbq") == "high" else "medium",
        "review_status": str(record.get("review_status", "")),
        "paper_id": paper_id,
        "year": record.get("year", ""),
        "venue": str(record.get("venue") or record.get("source_label") or ""),
        "authors": _normalize_list(record.get("authors") or []),
        "notion_page_id": str(record.get("notion_page_id") or ""),
        "source_url": str(record.get("source_url") or ""),
        "benchmark_name": str(extraction.get("benchmark_name") or ""),
        "benchmark_role": str(extraction.get("benchmark_role") or ""),
        "bias_type": str(extraction.get("bias_type") or ""),
        "translation_based": extraction.get("translation_based"),
        "cross_lingual_comparison": extraction.get("cross_lingual_comparison_present"),
        "human_evaluation_used": extraction.get("human_evaluation_used"),
        "frenchbbq_relevance": str(extraction.get("relevance_to_frenchbbq") or ""),
        "unified_multilingual_bbq_relevance": str(extraction.get("relevance_to_multilingual_unified_bbq") or ""),
        "review_project_id": project.review_project_id,
    }
    body_lines = [
        _dump_frontmatter(frontmatter).strip(),
        "",
        f"# {title}",
        "",
        "# Why this paper matters now",
        "",
        rationale or "待补充。",
        "",
        "# Summary",
        "",
        summary or "待补充。",
        "",
        "# Connections",
        f"- [[projects/{project.review_project_id}]]",
        f"- [[projects/multilingual-unified-bbq]]" if project.review_project_id == "multilingual-bias-benchmark-landscape" else "- [[projects/thesis]]",
        "",
    ]
    return "\n".join(body_lines).strip() + "\n"


def _update_paper_frontmatter(project, record: dict[str, Any], extraction: dict[str, Any], text: str) -> str:
    frontmatter, body = _split_frontmatter(text)
    title = str(record.get("title") or frontmatter.get("title") or _title_from_body(body) or record.get("paper_id") or "Untitled")
    paper_id = str(record.get("paper_id") or frontmatter.get("paper_id") or "").strip()
    today = datetime.now().strftime("%Y-%m-%d")

    tags = list(dict.fromkeys(_normalize_list(frontmatter.get("tags")) + ["paper", project.source_topic_slug, "review-aligned"]))
    if extraction.get("bias_type"):
        tags.append(str(extraction.get("bias_type")))
    tags = list(dict.fromkeys(tags))

    review_directions = list(dict.fromkeys(_normalize_list(frontmatter.get("research_directions")) + _normalize_list(extraction.get("review_gap_tags"))))
    language_scope = _normalize_list(extraction.get("language_scope")) or _normalize_list(frontmatter.get("language_scope"))
    frontmatter.update(
        {
            "title": title,
            "updated": today,
            "type": "paper",
            "tags": tags,
            "notion_url": str(record.get("notion_url") or frontmatter.get("notion_url") or ""),
            "status": frontmatter.get("status") or "active",
            "aliases": list(dict.fromkeys(_normalize_list(frontmatter.get("aliases")) + [title])),
            "area": project.source_topic_slug,
            "project": frontmatter.get("project") or "thesis",
            "language_scope": language_scope,
            "priority": "high" if extraction.get("relevance_to_multilingual_unified_bbq") == "high" else (frontmatter.get("priority") or "medium"),
            "review_status": str(record.get("review_status") or frontmatter.get("review_status") or ""),
            "paper_id": paper_id,
            "year": record.get("year") if record.get("year") not in (None, "") else frontmatter.get("year", ""),
            "venue": str(record.get("venue") or frontmatter.get("venue") or record.get("source_label") or ""),
            "authors": _normalize_list(record.get("authors") or frontmatter.get("authors") or []),
            "notion_page_id": str(record.get("notion_page_id") or frontmatter.get("notion_page_id") or ""),
            "source_url": str(record.get("source_url") or frontmatter.get("source_url") or ""),
            "benchmark_name": str(extraction.get("benchmark_name") or frontmatter.get("benchmark_name") or ""),
            "benchmark_role": str(extraction.get("benchmark_role") or frontmatter.get("benchmark_role") or ""),
            "bias_type": str(extraction.get("bias_type") or frontmatter.get("bias_type") or ""),
            "translation_based": extraction.get("translation_based") if extraction.get("translation_based") is not None else frontmatter.get("translation_based"),
            "cross_lingual_comparison": extraction.get("cross_lingual_comparison_present") if extraction.get("cross_lingual_comparison_present") is not None else frontmatter.get("cross_lingual_comparison"),
            "human_evaluation_used": extraction.get("human_evaluation_used") if extraction.get("human_evaluation_used") is not None else frontmatter.get("human_evaluation_used"),
            "frenchbbq_relevance": str(extraction.get("relevance_to_frenchbbq") or frontmatter.get("frenchbbq_relevance") or ""),
            "unified_multilingual_bbq_relevance": str(extraction.get("relevance_to_multilingual_unified_bbq") or frontmatter.get("unified_multilingual_bbq_relevance") or ""),
            "research_directions": review_directions or frontmatter.get("research_directions") or [],
            "review_project_id": project.review_project_id,
        }
    )
    return _dump_frontmatter(frontmatter) + "\n" + body.lstrip()


def _replace_or_append_block(text: str, block: str) -> str:
    if START in text and END in text:
        before = text.split(START)[0].rstrip()
        after = text.split(END, 1)[1].lstrip()
        body = before + "\n\n" + block
        if after:
            body += "\n\n" + after
        return body.strip() + "\n"
    text = text.rstrip() + "\n\n" if text.strip() else ""
    return text + block + "\n"


def _paper_review_block(project, record: dict[str, Any], extraction: dict[str, Any]) -> str:
    thesis_rel = extraction.get("relevance_to_multilingual_unified_bbq") or extraction.get("relevance_to_frenchbbq") or extraction.get("thesis_relevance") or ""
    lines = [
        START,
        "## Review sync",
        f"- Review project: `{project.review_project_id}`",
        f"- Decision: `{record.get('screening_decision', '')}`",
        f"- Confidence: `{record.get('screening_confidence', '')}`",
    ]
    if thesis_rel:
        lines.append(f"- Thesis relevance: `{thesis_rel}`")
    for key, label in [
        ("benchmark_name", "Benchmark"),
        ("benchmark_role", "Benchmark role"),
        ("language_scope", "Language scope"),
        ("language_count", "Language count"),
        ("bias_type", "Bias type"),
        ("translation_based", "Translation based"),
        ("cross_lingual_comparison_present", "Cross-lingual comparison"),
        ("human_evaluation_used", "Human evaluation used"),
        ("relevance_to_frenchbbq", "FrenchBBQ relevance"),
        ("relevance_to_multilingual_unified_bbq", "Unified multilingual BBQ relevance"),
    ]:
        value = extraction.get(key)
        if value not in (None, "", []):
            lines.append(f"- {label}: `{value}`")
    languages = extraction.get("languages") or []
    if languages:
        lines.append("- Languages: `" + ", ".join(str(x) for x in languages[:12]) + "`")
    rationale = str(record.get("screening_rationale", "")).strip()
    if rationale:
        lines += ["", "### Review rationale", rationale]
    gaps = extraction.get("review_gap_tags") or []
    if gaps:
        lines += ["", "### Gap tags"]
        lines.extend(f"- {g}" for g in gaps)
    lines.append(END)
    return "\n".join(lines)


def _review_note_content(project, records: list[dict[str, Any]], extraction_rows: list[dict[str, Any]], synthesis_text: str, idea_slate_text: str = "", gap_summary_text: str = "", reading_queue_text: str = "", digest_text: str = "") -> str:
    by_paper = {row.get("paper_id", ""): row.get("extraction") or {} for row in extraction_rows}
    include_titles = [r.get("title", "") for r in records if r.get("screening_decision") == "include"]
    exclude_titles = [r.get("title", "") for r in records if r.get("screening_decision") == "exclude"]
    lines = [
        "---",
        f"title: \"{project.review_project_name}\"",
        f"type: review-project",
        f"review_project_id: \"{project.review_project_id}\"",
        f"source_topic_slug: \"{project.source_topic_slug}\"",
        "---",
        "",
        f"# {project.review_project_name}",
        "",
        f"**Objective:** {project.objective}",
        "",
        f"- Topic map: [[reviews/{project.review_project_id}-map]]",
        "",
        "## Research questions",
    ]
    lines.extend(f"- {q}" for q in project.research_questions)
    lines += ["", "## Included papers"]
    if include_titles:
        for title in include_titles:
            lines.append(f"- {title}")
    else:
        lines.append("- None yet")
    lines += ["", "## Excluded papers"]
    if exclude_titles:
        for title in exclude_titles[:20]:
            lines.append(f"- {title}")
    else:
        lines.append("- None")
    lines += ["", "## Extraction highlights"]
    for paper_id, extraction in by_paper.items():
        bits = []
        for key in ("benchmark_name", "benchmark_role", "language_scope", "bias_type", "relevance_to_multilingual_unified_bbq"):
            val = extraction.get(key)
            if val not in (None, "", []):
                bits.append(f"{key}={val}")
        lines.append(f"- `{paper_id}`: " + (", ".join(bits) if bits else "no key extracted fields"))
    lines += ["", synthesis_text.strip(), ""]
    if gap_summary_text.strip():
        lines += [gap_summary_text.strip(), ""]
    if reading_queue_text.strip():
        lines += [reading_queue_text.strip(), ""]
    if digest_text.strip():
        lines += [digest_text.strip(), ""]
    if idea_slate_text.strip():
        lines += [idea_slate_text.strip(), ""]
    return "\n".join(lines)


def _render_link_list(items: list[tuple[str, str]]) -> list[str]:
    if not items:
        return ["- None yet"]
    return [f"- [[papers/{paper_id}]] — {title}" for paper_id, title in items]


def _review_map_content(project, records: list[dict[str, Any]], extraction_rows: list[dict[str, Any]]) -> str:
    extraction_by_paper = {row.get("paper_id", ""): row.get("extraction") or {} for row in extraction_rows}
    included = [r for r in records if r.get("screening_decision") == "include"]

    high_priority: list[tuple[str, str]] = []
    french_high: list[tuple[str, str]] = []
    translation_based: list[tuple[str, str]] = []
    native_authored: list[tuple[str, str]] = []
    cross_lingual: list[tuple[str, str]] = []
    by_bias: dict[str, list[tuple[str, str]]] = {}
    by_role: dict[str, list[tuple[str, str]]] = {}

    for record in included:
        paper_id = str(record.get("paper_id", "")).strip()
        if not paper_id:
            continue
        title = str(record.get("title", "Untitled")).strip()
        extraction = extraction_by_paper.get(paper_id, {})
        pair = (paper_id, title)
        if extraction.get("relevance_to_multilingual_unified_bbq") == "high":
            high_priority.append(pair)
        if extraction.get("relevance_to_frenchbbq") == "high":
            french_high.append(pair)
        if extraction.get("translation_based"):
            translation_based.append(pair)
        if extraction.get("native_authored_data"):
            native_authored.append(pair)
        if extraction.get("cross_lingual_comparison_present"):
            cross_lingual.append(pair)
        bias = str(extraction.get("bias_type") or "other")
        by_bias.setdefault(bias, []).append(pair)
        role = str(extraction.get("benchmark_role") or "unknown")
        by_role.setdefault(role, []).append(pair)

    lines = [
        "---",
        f"title: \"{project.review_project_name} Map\"",
        "type: review-project-map",
        f"review_project_id: \"{project.review_project_id}\"",
        f"source_topic_slug: \"{project.source_topic_slug}\"",
        "---",
        "",
        f"# {project.review_project_name} — Topic Map",
        "",
        f"- Canonical review note: [[reviews/{project.review_project_id}]]",
        f"- Included papers: {len(included)}",
        f"- High unified-BBQ relevance: {len(high_priority)}",
        f"- High FrenchBBQ relevance: {len(french_high)}",
        f"- Translation-based benchmarks: {len(translation_based)}",
        f"- Native-authored signals: {len(native_authored)}",
        f"- Explicit cross-lingual comparison: {len(cross_lingual)}",
        "",
        "## Core reading lanes",
        "",
        "### High-value unified multilingual BBQ references",
    ]
    lines.extend(_render_link_list(high_priority[:25]))
    lines += ["", "### High-value FrenchBBQ references"]
    lines.extend(_render_link_list(french_high[:25]))
    lines += ["", "### Translation-based benchmark family"]
    lines.extend(_render_link_list(translation_based[:25]))
    lines += ["", "### Native-authored / co-designed benchmark family"]
    lines.extend(_render_link_list(native_authored[:25]))
    lines += ["", "### Explicit cross-lingual comparison papers"]
    lines.extend(_render_link_list(cross_lingual[:25]))
    lines += ["", "## Grouped by benchmark role"]
    for role in sorted(by_role):
        lines += ["", f"### {role} ({len(by_role[role])})"]
        lines.extend(_render_link_list(by_role[role][:25]))
    lines += ["", "## Grouped by bias type"]
    for bias in sorted(by_bias):
        lines += ["", f"### {bias} ({len(by_bias[bias])})"]
        lines.extend(_render_link_list(by_bias[bias][:25]))
    lines.append("")
    return "\n".join(lines)


def sync_review_to_obsidian(project, records: list[dict[str, Any]], extraction_rows: list[dict[str, Any]], synthesis_text: str, idea_slate_text: str = "", gap_summary_text: str = "", reading_queue_text: str = "", digest_text: str = "") -> dict[str, Any]:
    vault = get_obsidian_vault()
    review_note = _review_note_path(project)
    review_map = _review_map_path(project)
    review_note.parent.mkdir(parents=True, exist_ok=True)
    review_note.write_text(
        _review_note_content(
            project,
            records,
            extraction_rows,
            synthesis_text,
            idea_slate_text=idea_slate_text,
            gap_summary_text=gap_summary_text,
            reading_queue_text=reading_queue_text,
            digest_text=digest_text,
        ),
        encoding="utf-8",
    )
    review_map.write_text(_review_map_content(project, records, extraction_rows), encoding="utf-8")

    extraction_by_paper = {row.get("paper_id", ""): row.get("extraction") or {} for row in extraction_rows}
    extraction_row_by_paper = {row.get("paper_id", ""): row for row in extraction_rows}
    updated_paper_notes: list[str] = []
    created_paper_notes: list[str] = []
    for record in records:
        paper_id = str(record.get("paper_id", "")).strip()
        if not paper_id:
            continue
        path = _paper_note_path(paper_id)
        extraction_row = extraction_row_by_paper.get(paper_id, {})
        effective_record = dict(record)
        effective_record.update({k: v for k, v in extraction_row.items() if k != "extraction"})
        extraction = extraction_by_paper.get(paper_id, {})
        if path.exists():
            text = path.read_text(encoding="utf-8")
            text = _update_paper_frontmatter(project, effective_record, extraction, text)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = _paper_note_stub(project, effective_record, extraction)
            created_paper_notes.append(str(path))
        block = _paper_review_block(project, effective_record, extraction)
        updated = _replace_or_append_block(text, block)
        path.write_text(updated, encoding="utf-8")
        updated_paper_notes.append(str(path))

    return {
        "vault": str(vault),
        "review_note_path": str(review_note),
        "review_map_path": str(review_map),
        "updated_paper_notes": updated_paper_notes,
        "created_paper_notes": created_paper_notes,
    }
