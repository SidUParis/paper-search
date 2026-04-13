"""Write review-layer results back to Notion."""

from __future__ import annotations

from typing import Any

from paper_search.review_store import get_review_dir, load_jsonl
from paper_search.topics import get_topic

REVIEW_PROPERTY_SCHEMAS = {
    "Review Project": {"rich_text": {}},
    "Review Status": {
        "select": {
            "options": [
                {"name": "screened_include", "color": "green"},
                {"name": "screened_exclude", "color": "red"},
                {"name": "screened_maybe", "color": "yellow"},
                {"name": "extracted", "color": "blue"},
                {"name": "synthesized", "color": "purple"},
            ]
        }
    },
    "Relevance Score": {"number": {"format": "number"}},
    "Thesis Relevance": {
        "select": {
            "options": [
                {"name": "low", "color": "gray"},
                {"name": "medium", "color": "yellow"},
                {"name": "high", "color": "green"},
            ]
        }
    },
    "Review Notes": {"rich_text": {}},
    "Paper Type": {"select": {}},
    "Benchmark Role": {"select": {}},
    "Language Scope": {"select": {}},
    "Language Count": {"number": {"format": "number"}},
    "Bias Type": {"select": {}},
    "Benchmark Name": {"rich_text": {}},
    "Translation Based": {"checkbox": {}},
    "Cross-Lingual Comparison": {"checkbox": {}},
    "Human Evaluation Used": {"checkbox": {}},
    "FrenchBBQ Relevance": {
        "select": {
            "options": [
                {"name": "low", "color": "gray"},
                {"name": "medium", "color": "yellow"},
                {"name": "high", "color": "green"},
            ]
        }
    },
    "Unified Multilingual BBQ Relevance": {
        "select": {
            "options": [
                {"name": "low", "color": "gray"},
                {"name": "medium", "color": "yellow"},
                {"name": "high", "color": "green"},
            ]
        }
    },
    "Review Gaps": {"rich_text": {}},
    "Review Summary": {"rich_text": {}},
    "Idea Slate": {"rich_text": {}},
}

_REVIEW_CARD_TOGGLE_TITLE = "Research Review Card"


def get_notion_client():
    from paper_search.notion_sync import get_notion_client as _get_notion_client

    return _get_notion_client()


def _source_map_for_project(project) -> dict[str, str]:
    from paper_search.fulltext_pipeline import _iter_sources

    topic = get_topic(project.source_topic_slug)
    if not topic:
        raise ValueError(f"Topic '{project.source_topic_slug}' not found")
    return {label: ds_id for label, ds_id, _db_id in _iter_sources(topic, source="all")}


def _collect_source_labels(project) -> set[str]:
    review_dir = get_review_dir(project.review_project_id)
    records = load_jsonl(review_dir / "records.jsonl")
    return {str(r.get("source_label", "")).strip() for r in records if str(r.get("source_label", "")).strip()}


def ensure_review_properties(project, source_labels: set[str] | list[str] | None = None) -> None:
    client = get_notion_client()
    source_map = _source_map_for_project(project)
    labels = set(source_labels or source_map.keys())

    for label in labels:
        ds_id = source_map.get(label)
        if not ds_id:
            continue
        meta = client.data_sources.retrieve(data_source_id=ds_id)
        existing = set((meta.get("properties") or {}).keys())
        missing = {name: schema for name, schema in REVIEW_PROPERTY_SCHEMAS.items() if name not in existing}
        if missing:
            client.data_sources.update(data_source_id=ds_id, properties=missing)


def _pick_thesis_relevance(extraction: dict[str, Any]) -> str | None:
    for key in ("relevance_to_multilingual_unified_bbq", "relevance_to_frenchbbq", "thesis_relevance"):
        value = extraction.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _compact_review_notes(record: dict[str, Any], extraction: dict[str, Any]) -> str:
    bits = [
        f"project={record.get('review_project_id', '')}",
        f"decision={record.get('screening_decision', '')}",
    ]
    rationale = str(record.get("screening_rationale", "")).strip()
    if rationale:
        bits.append(f"rationale={rationale}")
    for key in (
        "language_scope",
        "bias_type",
        "benchmark_name",
        "benchmark_role",
        "translation_based",
        "cross_lingual_comparison_present",
        "human_evaluation_used",
        "relevance_to_frenchbbq",
        "relevance_to_multilingual_unified_bbq",
    ):
        value = extraction.get(key)
        if value not in (None, "", []):
            bits.append(f"{key}={value}")
    gaps = extraction.get("review_gap_tags") or []
    if gaps:
        bits.append("gaps=" + ", ".join(str(x) for x in gaps[:5]))
    text = " | ".join(bits)
    return text[:1900]


def _truncate_text(text: str, limit: int = 1900) -> str:
    return text.strip()[:limit] if text else ""


def _humanize_token(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("_", " ") if text else ""


def _bool_label(value: Any, true_label: str, false_label: str | None = None) -> str | None:
    if value is True:
        return true_label
    if value is False and false_label:
        return false_label
    return None


def _plain_text_from_rich_text(items: list[dict[str, Any]] | None) -> str:
    text_bits: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        plain_text = item.get("plain_text")
        if plain_text:
            text_bits.append(str(plain_text))
            continue
        text = item.get("text") or {}
        content = text.get("content")
        if content:
            text_bits.append(str(content))
    return "".join(text_bits).strip()


def _rich_text_payload(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": _truncate_text(text, 1900)}}]


def _block_title(block: dict[str, Any]) -> str:
    block_type = str(block.get("type", ""))
    payload = block.get(block_type) or {}
    return _plain_text_from_rich_text(payload.get("rich_text"))


def _per_paper_review_summary(record: dict[str, Any], extraction: dict[str, Any]) -> str:
    title = str(record.get("title", "")).strip()
    benchmark_name = str(extraction.get("benchmark_name") or "").strip()
    benchmark_role = str(extraction.get("benchmark_role") or "").strip()
    language_scope = _humanize_token(extraction.get("language_scope"))
    bias_type = _humanize_token(extraction.get("bias_type"))
    evaluation_target = _humanize_token(extraction.get("evaluation_target"))
    language_count = extraction.get("language_count")
    rationale = str(record.get("screening_rationale", "")).strip()
    generic_rationale = rationale.lower().startswith("fast-screened as in scope because")

    contribution_lead = {
        "introduces_benchmark": "introduces",
        "uses_existing_benchmark": "uses",
        "compares_benchmarks": "compares",
        "critique_of_benchmark": "critiques",
    }.get(benchmark_role, "contributes evidence for")
    benchmark_phrase = f" the benchmark '{benchmark_name}'" if benchmark_name else " benchmark-relevant evidence"

    sentence_one_parts = [f"This paper {contribution_lead}{benchmark_phrase}"]
    qualifiers = [item for item in (language_scope, bias_type) if item]
    if qualifiers:
        sentence_one_parts.append(f"in a {', '.join(qualifiers)} setting")
    if evaluation_target:
        sentence_one_parts.append(f"with a focus on {evaluation_target}")
    sentence_one = " ".join(sentence_one_parts).strip().rstrip(".") + "."

    sentence_two_bits: list[str] = []
    if extraction.get("translation_based") is True:
        sentence_two_bits.append("uses translation-based data construction")
    if extraction.get("native_authored_data") is True:
        sentence_two_bits.append("includes natively authored data")
    if extraction.get("cross_lingual_comparison_present") is True:
        sentence_two_bits.append("reports explicit cross-lingual comparisons")
    if extraction.get("human_evaluation_used") is True:
        sentence_two_bits.append("includes human evaluation")
    if language_count not in (None, ""):
        sentence_two_bits.append(f"covers {language_count} explicitly named languages")
    sentence_two = ""
    if sentence_two_bits:
        sentence_two = "The study " + "; ".join(sentence_two_bits) + "."

    relevance_bits: list[str] = []
    french = extraction.get("relevance_to_frenchbbq")
    unified = extraction.get("relevance_to_multilingual_unified_bbq")
    if french not in (None, ""):
        relevance_bits.append(f"FrenchBBQ relevance is {french}")
    if unified not in (None, ""):
        relevance_bits.append(f"unified multilingual BBQ relevance is {unified}")
    sentence_three = ""
    if relevance_bits:
        sentence_three = "For thesis planning, " + "; ".join(relevance_bits) + "."

    rationale_sentence = ""
    if rationale and not generic_rationale:
        rationale_sentence = f"Reviewer note: {rationale}"
    return _truncate_text(" ".join(x for x in (sentence_one, sentence_two, sentence_three, rationale_sentence) if x), 1900)


def _per_paper_idea_hook(project, extraction: dict[str, Any]) -> str:
    hooks: list[str] = []
    pid = getattr(project, 'review_project_id', '')
    if pid == 'multilingual-bias-benchmark-landscape':
        if extraction.get('native_authored_data'):
            hooks.append('use as evidence for native/co-designed benchmark construction')
        if extraction.get('translation_based'):
            hooks.append('use as evidence for translation-artifact risk analysis')
        if extraction.get('bias_type') == 'positional_bias':
            hooks.append('use as evidence that positional bias should be treated as an explicit benchmark axis')
        if extraction.get('benchmark_role') == 'introduces_benchmark':
            hooks.append('compare this benchmark design against FrenchBBQ / unified multilingual BBQ')
        if extraction.get('relevance_to_frenchbbq') == 'high':
            hooks.append('high-priority reference for FrenchBBQ design choices')
    elif pid == 'conversational-summarization-landscape':
        if extraction.get('evaluation_focus') == 'faithfulness':
            hooks.append('use as evidence for faithfulness-focused conversational summarization evaluation')
        if extraction.get('input_modality') == 'speech_or_transcript':
            hooks.append('use as evidence for spoken-dialogue or ASR-noise settings')
        if extraction.get('streaming_or_real_time'):
            hooks.append('use as evidence for real-time or streaming summarization constraints')
        if extraction.get('dialogue_domain') not in (None, '', 'other'):
            hooks.append(f"reference paper for {extraction.get('dialogue_domain')} dialogue setting")
    elif pid == 'sycophancy-evaluation-landscape':
        if extraction.get('evaluation_target') == 'measurement':
            hooks.append('use as evidence for benchmark/measurement design')
        if extraction.get('evaluation_target') == 'mitigation':
            hooks.append('use as evidence for mitigation baselines and evaluation')
        if extraction.get('feedback_loop_involved'):
            hooks.append('use as evidence linking sycophancy to RLHF/preference feedback loops')
        if extraction.get('setup_type') not in (None, '', 'other'):
            hooks.append(f"reference paper for {extraction.get('setup_type')} elicitation setup")
    gaps = extraction.get('review_gap_tags') or []
    if gaps:
        hooks.append('gap_tags=' + ', '.join(str(x) for x in gaps[:3]))
    return _truncate_text(' | '.join(dict.fromkeys(hooks)), 1900)


def _heading_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _rich_text_payload(text)}}


def _paragraph_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text_payload(text)}}


def _bullet_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text_payload(text)}}


def _build_research_card_blocks(record: dict[str, Any], extraction: dict[str, Any], project=None) -> list[dict[str, Any]]:
    summary = _per_paper_review_summary(record, extraction)
    idea_hook = _per_paper_idea_hook(project, extraction) if project is not None else ""

    evidence_lines = [
        f"Review status: {record.get('review_status', 'unknown')}",
        f"Screening decision: {record.get('screening_decision', 'unknown')}",
    ]
    if record.get("screening_confidence") not in (None, ""):
        evidence_lines.append(f"Relevance score: {round(float(record.get('screening_confidence', 0.0)) * 100, 2)}")
    rationale = str(record.get("screening_rationale", "")).strip()
    if rationale:
        evidence_lines.append(f"Screening rationale: {rationale}")

    extraction_lines: list[str] = []
    for label, value in [
        ("Paper type", extraction.get("paper_type")),
        ("Benchmark role", _humanize_token(extraction.get("benchmark_role"))),
        ("Benchmark name", extraction.get("benchmark_name")),
        ("Language scope", _humanize_token(extraction.get("language_scope"))),
        ("Language count", extraction.get("language_count")),
        ("Bias type", _humanize_token(extraction.get("bias_type"))),
        ("Evaluation target", _humanize_token(extraction.get("evaluation_target"))),
        ("Translation based", _bool_label(extraction.get("translation_based"), "yes", "no")),
        ("Native-authored data", _bool_label(extraction.get("native_authored_data"), "yes", "no")),
        ("Cross-lingual comparison", _bool_label(extraction.get("cross_lingual_comparison_present"), "yes", "no")),
        ("Human evaluation used", _bool_label(extraction.get("human_evaluation_used"), "yes", "no")),
        ("FrenchBBQ relevance", extraction.get("relevance_to_frenchbbq")),
        ("Unified multilingual BBQ relevance", extraction.get("relevance_to_multilingual_unified_bbq")),
    ]:
        if value not in (None, "", []):
            extraction_lines.append(f"{label}: {value}")
    languages = extraction.get("languages") or []
    if languages:
        extraction_lines.append("Languages: " + ", ".join(str(x) for x in languages[:12]))
    gaps = extraction.get("review_gap_tags") or []
    if gaps:
        extraction_lines.append("Gap tags: " + ", ".join(str(x) for x in gaps[:8]))

    children: list[dict[str, Any]] = [
        _heading_block("Research-use summary"),
        _paragraph_block(summary or "No review summary available yet."),
        _heading_block("Structured extraction highlights"),
    ]
    for line in extraction_lines or ["No structured extraction fields available yet."]:
        children.append(_bullet_block(str(line)))
    children.append(_heading_block("Review evidence"))
    for line in evidence_lines:
        children.append(_bullet_block(str(line)))
    if idea_hook:
        children.append(_heading_block("Benchmark-design hook"))
        children.append(_paragraph_block(idea_hook))

    return [
        {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": _rich_text_payload(_REVIEW_CARD_TOGGLE_TITLE),
                "children": children,
            },
        }
    ]


def _refresh_page_body(client, page_id: str, blocks: list[dict[str, Any]]) -> None:
    if not blocks:
        return
    try:
        existing = client.blocks.children.list(block_id=page_id, page_size=100)
    except Exception:
        existing = {"results": []}
    for child in existing.get("results", []):
        if _block_title(child) == _REVIEW_CARD_TOGGLE_TITLE:
            try:
                client.blocks.delete(block_id=child.get("id"))
            except Exception:
                pass
    client.blocks.children.append(block_id=page_id, children=blocks)


def _build_page_properties(record: dict[str, Any], extraction: dict[str, Any], project=None) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Review Project": {"rich_text": [{"text": {"content": str(record.get("review_project_id", ""))[:2000]}}]},
        "Review Status": {"select": {"name": str(record.get("review_status", ""))[:100]}},
        "Relevance Score": {"number": round(float(record.get("screening_confidence", 0.0)) * 100, 2)},
        "Review Notes": {"rich_text": [{"text": {"content": _compact_review_notes(record, extraction)}}]},
    }
    thesis_relevance = _pick_thesis_relevance(extraction)
    if thesis_relevance:
        props["Thesis Relevance"] = {"select": {"name": thesis_relevance[:100]}}
    if extraction.get("paper_type"):
        props["Paper Type"] = {"select": {"name": str(extraction.get("paper_type"))[:100]}}
    if extraction.get("benchmark_role"):
        props["Benchmark Role"] = {"select": {"name": str(extraction.get("benchmark_role"))[:100]}}
    if extraction.get("language_scope"):
        props["Language Scope"] = {"select": {"name": str(extraction.get("language_scope"))[:100]}}
    if extraction.get("language_count") not in (None, ""):
        props["Language Count"] = {"number": int(extraction.get("language_count"))}
    if extraction.get("bias_type"):
        props["Bias Type"] = {"select": {"name": str(extraction.get("bias_type"))[:100]}}
    if extraction.get("benchmark_name") not in (None, ""):
        props["Benchmark Name"] = {"rich_text": [{"text": {"content": str(extraction.get("benchmark_name"))[:2000]}}]}
    if extraction.get("translation_based") is not None:
        props["Translation Based"] = {"checkbox": bool(extraction.get("translation_based"))}
    if extraction.get("cross_lingual_comparison_present") is not None:
        props["Cross-Lingual Comparison"] = {"checkbox": bool(extraction.get("cross_lingual_comparison_present"))}
    if extraction.get("human_evaluation_used") is not None:
        props["Human Evaluation Used"] = {"checkbox": bool(extraction.get("human_evaluation_used"))}
    if extraction.get("relevance_to_frenchbbq"):
        props["FrenchBBQ Relevance"] = {"select": {"name": str(extraction.get("relevance_to_frenchbbq"))[:100]}}
    if extraction.get("relevance_to_multilingual_unified_bbq"):
        props["Unified Multilingual BBQ Relevance"] = {
            "select": {"name": str(extraction.get("relevance_to_multilingual_unified_bbq"))[:100]}
        }
    gaps = extraction.get("review_gap_tags") or []
    if gaps:
        props["Review Gaps"] = {"rich_text": [{"text": {"content": ', '.join(str(x) for x in gaps)[:2000]}}]}
    review_summary = _per_paper_review_summary(record, extraction)
    if review_summary:
        props["Review Summary"] = {"rich_text": [{"text": {"content": review_summary}}]}
    idea_hook = _per_paper_idea_hook(project, extraction) if project is not None else ""
    if idea_hook:
        props["Idea Slate"] = {"rich_text": [{"text": {"content": idea_hook}}]}
    return props


def write_review_results_to_notion(project) -> dict[str, int]:
    client = get_notion_client()
    review_dir = get_review_dir(project.review_project_id)
    records = load_jsonl(review_dir / "records.jsonl")
    extractions = load_jsonl(review_dir / "extractions.jsonl")
    extraction_by_page = {row.get("notion_page_id", ""): row for row in extractions}
    extraction_payload_by_page = {row.get("notion_page_id", ""): row.get("extraction") or {} for row in extractions}

    updated = 0
    skipped = 0
    for record in records:
        page_id = str(record.get("notion_page_id", "")).strip()
        if not page_id:
            skipped += 1
            continue
        extraction_row = extraction_by_page.get(page_id)
        effective_record = dict(record)
        if extraction_row:
            effective_record.update({k: v for k, v in extraction_row.items() if k != "extraction"})
        extraction = extraction_payload_by_page.get(page_id, {})
        properties = _build_page_properties(effective_record, extraction, project=project)
        client.pages.update(page_id=page_id, properties=properties)
        _refresh_page_body(client, page_id, _build_research_card_blocks(effective_record, extraction, project=project))
        updated += 1
    return {"updated": updated, "skipped": skipped}
