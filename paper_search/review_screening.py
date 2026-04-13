"""Screen papers for a review project."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from paper_search.summarizer import get_llm_client


def _screening_messages(project, candidate: dict[str, Any], model: str) -> list[dict[str, str]]:
    schema = {
        "decision": "include|exclude|maybe",
        "confidence": "float 0..1",
        "rationale": "short explanation",
        "criteria_matched": ["..."],
        "criteria_failed": ["..."],
    }
    prompt = f"""
You are screening a paper for a structured literature review.

Review project: {project.review_project_name}
Objective: {project.objective}
Research questions:
""".strip()
    prompt += "\n" + "\n".join(f"- {q}" for q in project.research_questions)
    prompt += "\n\nInclusion criteria:\n" + "\n".join(f"- {c}" for c in project.inclusion_criteria)
    prompt += "\n\nExclusion criteria:\n" + "\n".join(f"- {c}" for c in project.exclusion_criteria)
    prompt += (
        f"\n\nPaper title: {candidate.get('title', '')}"
        f"\nAbstract: {candidate.get('abstract', '') or 'N/A'}"
        f"\nExisting summary: {candidate.get('summary', '') or 'N/A'}"
        f"\nChinese brief: {candidate.get('zh_brief', '') or 'N/A'}"
        f"\nPaper limitations: {candidate.get('paper_limitations', []) or 'N/A'}"
        "\n\nReturn strict JSON only with this schema:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n"
        "Do not use prior knowledge. Base the decision only on the provided evidence."
    )
    if "gemma" in model.lower():
        return [{"role": "user", "content": prompt}]
    return [
        {"role": "system", "content": "You are a careful systematic literature review screener. Return strict JSON only."},
        {"role": "user", "content": prompt},
    ]


def _fast_screen_candidate(project, candidate: dict[str, Any]) -> dict[str, Any] | None:
    text = " ".join(
        str(candidate.get(k, "") or "")
        for k in ("title", "abstract", "summary", "zh_brief")
    ).lower()

    if project.review_project_id == 'conversational-summarization-landscape':
        conversational_signals = [
            r'conversational', r'conversation', r'dialogue', r'dialog', r'dialogsum', r'samsum',
            r'qmsum', r'meeting', r'meetingbank', r'mediasum', r'chat', r'multi-turn', r'spoken',
        ]
        summarization_signals = [r'summarization', r'summarisation', r'summary', r'summarizer', r'summariser']
        study_signals = [
            r'benchmark', r'dataset', r'evaluation', r'shared task', r'challenge', r'survey', r'review',
            r'model', r'approach', r'framework', r'method', r'faithful', r'hallucination',
        ]
        has_conv = any(re.search(p, text) for p in conversational_signals)
        has_sum = any(re.search(p, text) for p in summarization_signals)
        has_study = any(re.search(p, text) for p in study_signals)

        if has_conv and has_sum and has_study:
            return {
                "decision": "include",
                "confidence": 0.92,
                "rationale": "Fast-screened as in scope because the paper clearly targets conversational/dialogue summarization and appears to contribute an empirical benchmark, method, evaluation, or survey.",
                "criteria_matched": [
                    "conversational or dialogue summarization focus",
                    "empirical benchmark, method, evaluation, or survey contribution",
                ],
                "criteria_failed": [],
            }
        if has_sum and not has_conv:
            return {
                "decision": "exclude",
                "confidence": 0.93,
                "rationale": "Fast-screened as out of scope because the paper is about summarization but does not show conversational/dialogue/meeting/chat evidence.",
                "criteria_matched": ["summarization focus"],
                "criteria_failed": ["conversational or dialogue summarization focus"],
            }
        if has_conv and not has_sum:
            return {
                "decision": "exclude",
                "confidence": 0.9,
                "rationale": "Fast-screened as out of scope because the paper concerns dialogue/conversation but does not appear to study summarization.",
                "criteria_matched": ["conversational or dialogue setting"],
                "criteria_failed": ["summarization focus"],
            }
        return None

    if project.review_project_id == 'sycophancy-evaluation-landscape':
        sycophancy_signals = [
            r'sycophan', r'user-belief', r'user belief', r'agreeableness bias', r'flattery',
            r'belief mirroring', r'opinion mirroring', r'alignment faking', r'reward hacking',
            r'preference mimicry', r'echoing user views',
        ]
        study_signals = [
            r'benchmark', r'dataset', r'evaluation', r'evaluate', r'analysis', r'probe', r'probing',
            r'mitigation', r'intervention', r'study', r'survey', r'measure', r'measurement',
        ]
        general_alignment_signals = [r'alignment', r'rlhf', r'preference optimization', r'reinforcement learning']
        has_sycophancy = any(re.search(p, text) for p in sycophancy_signals)
        has_study = any(re.search(p, text) for p in study_signals)
        has_alignment = any(re.search(p, text) for p in general_alignment_signals)

        if has_sycophancy and (has_study or has_alignment):
            return {
                "decision": "include",
                "confidence": 0.92,
                "rationale": "Fast-screened as in scope because the paper clearly studies LLM sycophancy or closely related user-opinion/alignment-faking behavior with empirical analysis, evaluation, or mitigation.",
                "criteria_matched": [
                    "focuses on sycophancy or closely related agreement-seeking behavior",
                    "contains empirical evaluation, analysis, benchmark, or mitigation evidence",
                ],
                "criteria_failed": [],
            }
        if has_alignment and not has_sycophancy:
            return {
                "decision": "exclude",
                "confidence": 0.9,
                "rationale": "Fast-screened as out of scope because the paper appears to address general alignment or RLHF without clear sycophancy-specific evidence.",
                "criteria_matched": ["LLM alignment-related topic"],
                "criteria_failed": ["focuses on sycophancy or closely related agreement-seeking behavior"],
            }
        return None

    multilingual_signals = [
        r"multilingual", r"multi-lingual", r"cross-lingual", r"cross lingual", r"beyond english",
        r"non-english", r"across languages", r"multiple languages", r"spoken lms", r"voicebbq",
        r"basqu?e", r"french", r"arabic", r"spanish", r"hindi", r"chinese", r"swahili", r"low-resource",
    ]
    english_only_signals = [r"english-only", r"english only", r"english benchmark", r"bbq", r"stereoset", r"crows-pairs"]
    benchmark_signals = [r"benchmark", r"dataset", r"evaluation", r"systematic review", r"survey", r"review"]
    method_signals = [r"mitigation", r"debias", r"steering", r"prompt", r"fine-tuning", r"training", r"method", r"approach"]

    negative_multi_signals = [r'no cross-lingual', r'no multilingual', r'without cross-lingual', r'without multilingual', r'english-only']
    has_negative_multi = any(re.search(p, text) for p in negative_multi_signals)
    has_multi = any(re.search(p, text) for p in multilingual_signals) and not has_negative_multi
    has_english_only = any(re.search(p, text) for p in english_only_signals)
    has_benchmark = any(re.search(p, text) for p in benchmark_signals)
    has_method = any(re.search(p, text) for p in method_signals)

    if has_multi and has_benchmark:
        return {
            "decision": "include",
            "confidence": 0.93,
            "rationale": "Fast-screened as in scope because the paper clearly signals a multilingual or cross-lingual benchmark/evaluation contribution relevant to this review project.",
            "criteria_matched": ["benchmark or evaluation focused", "multilingual or cross-lingual setting"],
            "criteria_failed": [],
        }

    if not has_multi and has_english_only:
        return {
            "decision": "exclude",
            "confidence": 0.95,
            "rationale": "Fast-screened as out of scope: the paper appears to focus on English-only or non-multilingual bias evaluation and does not show multilingual/cross-lingual evidence relevant to this review project.",
            "criteria_matched": ["empirical paper"] if any(x in text for x in ["benchmark", "evaluation", "bias"]) else [],
            "criteria_failed": ["multilingual or cross-lingual setting"],
        }

    if project.review_project_id == 'multilingual-bias-benchmark-landscape':
        if has_multi and has_benchmark:
            return {
                "decision": "include",
                "confidence": 0.93,
                "rationale": "Fast-screened as in scope because the paper clearly signals a multilingual or cross-lingual benchmark/evaluation/review contribution relevant to this project.",
                "criteria_matched": ["benchmark or evaluation focused", "multilingual or cross-lingual setting"],
                "criteria_failed": [],
            }
        return {
            "decision": "exclude",
            "confidence": 0.9,
            "rationale": "Fast-screened as out of scope for the multilingual benchmark landscape project because the candidate does not clearly satisfy both multilingual/cross-lingual scope and benchmark/evaluation/review focus.",
            "criteria_matched": ["benchmark or evaluation focused"] if has_benchmark else [],
            "criteria_failed": [x for x, ok in [("multilingual or cross-lingual setting", has_multi), ("benchmark or evaluation focused", has_benchmark)] if not ok],
        }

    if not has_multi and not has_benchmark and has_method:
        return {
            "decision": "exclude",
            "confidence": 0.93,
            "rationale": "Fast-screened as out of scope because the paper appears to focus on a method or mitigation approach rather than a multilingual benchmark/evaluation landscape target for this review project.",
            "criteria_matched": ["directly studies bias, fairness, stereotypes, toxicity, or disparity"] if 'bias' in text or 'fairness' in text else [],
            "criteria_failed": ["benchmark or evaluation focused", "multilingual or cross-lingual setting"],
        }

    if not has_multi and "language" not in text and "lingual" not in text:
        return {
            "decision": "exclude",
            "confidence": 0.9,
            "rationale": "Fast-screened as likely out of scope because no multilingual, cross-lingual, or language-coverage evidence appears in the title/abstract/summary for this review project.",
            "criteria_matched": [],
            "criteria_failed": ["multilingual or cross-lingual setting"],
        }

    return None


def screen_candidate(project, candidate: dict[str, Any], max_retries: int = 3) -> dict[str, Any]:
    fast = _fast_screen_candidate(project, candidate)
    if fast is not None:
        return fast

    client, model = get_llm_client()
    messages = _screening_messages(project, candidate, model)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=500,
                temperature=0.1,
            )
            text = (response.choices[0].message.content or "").strip() if response.choices else ""
            data = json.loads(text)
            return {
                "decision": data["decision"],
                "confidence": float(data["confidence"]),
                "rationale": str(data["rationale"]).strip(),
                "criteria_matched": list(data.get("criteria_matched") or []),
                "criteria_failed": list(data.get("criteria_failed") or []),
            }
        except Exception as e:
            last_error = e
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
                continue
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            raise last_error
    raise last_error or RuntimeError("screening failed")


def build_review_record(project, candidate: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
    decision = screening["decision"]
    review_status = {
        "include": "screened_include",
        "exclude": "screened_exclude",
        "maybe": "screened_maybe",
    }.get(decision, "needs_human_review")
    return {
        "review_project_id": project.review_project_id,
        "notion_page_id": candidate.get("notion_page_id", ""),
        "paper_id": candidate.get("paper_id", ""),
        "title": candidate.get("title", ""),
        "authors": candidate.get("authors") or [],
        "year": candidate.get("year", ""),
        "topic_slug": candidate.get("topic_slug", ""),
        "abstract": candidate.get("abstract", ""),
        "summary": candidate.get("summary", ""),
        "zh_brief": candidate.get("zh_brief", ""),
        "paper_limitations": candidate.get("paper_limitations") or [],
        "source_url": candidate.get("source_url", ""),
        "venue": candidate.get("venue", ""),
        "source_label": candidate.get("source_label", ""),
        "screened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "screening_decision": decision,
        "screening_confidence": screening["confidence"],
        "screening_rationale": screening["rationale"],
        "criteria_matched": screening.get("criteria_matched") or [],
        "criteria_failed": screening.get("criteria_failed") or [],
        "review_status": review_status,
        "human_override": None,
    }
