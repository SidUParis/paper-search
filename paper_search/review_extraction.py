"""Structured extraction for included review records."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from openai import OpenAI
from paper_search.qwen_precompute import get_cached_review_extraction
from paper_search.summarizer import get_llm_client


_GENERIC_BENCHMARK_NAMES = {
    'benchmark', 'benchmarks', 'benchmarking', 'dataset', 'datasets', 'review', 'survey', 'evaluation', 'evaluations'
}


def _clean_benchmark_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().strip('.,:;()[]{}').lower()
    if not cleaned or cleaned in _GENERIC_BENCHMARK_NAMES:
        return None
    return cleaned


def _title_prefix_benchmark_name(title: str) -> str | None:
    if ':' not in title:
        return None
    prefix = title.split(':', 1)[0].strip()
    if not prefix:
        return None
    if len(prefix.split()) > 4:
        return None
    return _clean_benchmark_name(prefix)


def _schema_summary(project) -> str:
    lines = []
    for field in project.topic_schema:
        name = field.get("name", "")
        ftype = field.get("type", "text")
        desc = field.get("description", "")
        allowed = field.get("allowed_values") or []
        allowed_text = f" Allowed values: {allowed}." if allowed else ""
        lines.append(f"- {name}: {ftype}. {desc}{allowed_text}")
    return "\n".join(lines)


_HYBRID_FALLBACK_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    'multilingual-bias-benchmark-landscape': [
        {'name': 'paper_type', 'type': 'enum', 'allowed': ['benchmark', 'survey']},
        {'name': 'benchmark_role', 'type': 'enum', 'allowed': ['introduces_benchmark', 'uses_existing_benchmark', 'compares_benchmarks', 'critique_of_benchmark']},
        {'name': 'benchmark_name', 'type': 'text'},
        {'name': 'bias_type', 'type': 'enum', 'allowed': ['stereotype', 'toxicity', 'fairness', 'cultural_bias', 'performance_disparity', 'positional_bias', 'allocational_harm', 'representational_harm', 'other']},
        {'name': 'language_scope', 'type': 'enum', 'allowed': ['monolingual', 'multilingual', 'cross_lingual', 'code_switching']},
        {'name': 'languages', 'type': 'list[text]'},
        {'name': 'language_count', 'type': 'integer'},
        {'name': 'translation_based', 'type': 'boolean'},
        {'name': 'native_authored_data', 'type': 'boolean'},
        {'name': 'protected_attributes', 'type': 'list[text]'},
        {'name': 'evaluation_target', 'type': 'enum', 'allowed': ['discriminative', 'generative', 'open_ended', 'preference', 'ranking', 'judge_based']},
        {'name': 'human_evaluation_used', 'type': 'boolean'},
        {'name': 'cross_lingual_comparison_present', 'type': 'boolean'},
    ],
    'conversational-summarization-landscape': [
        {'name': 'paper_type', 'type': 'enum', 'allowed': ['benchmark', 'survey', 'method']},
        {'name': 'benchmark_name', 'type': 'text'},
        {'name': 'dialogue_domain', 'type': 'enum', 'allowed': ['meeting', 'customer_support', 'medical', 'social_media', 'open_domain_chat', 'other']},
        {'name': 'input_modality', 'type': 'enum', 'allowed': ['text_only', 'speech_or_transcript', 'multimodal']},
        {'name': 'evaluation_focus', 'type': 'enum', 'allowed': ['summary_quality', 'faithfulness', 'user_satisfaction', 'efficiency', 'other']},
        {'name': 'llm_used', 'type': 'boolean'},
        {'name': 'multilingual_or_crosslingual', 'type': 'boolean'},
        {'name': 'streaming_or_real_time', 'type': 'boolean'},
    ],
    'sycophancy-evaluation-landscape': [
        {'name': 'paper_type', 'type': 'enum', 'allowed': ['benchmark', 'survey', 'analysis', 'method']},
        {'name': 'benchmark_name', 'type': 'text'},
        {'name': 'setup_type', 'type': 'enum', 'allowed': ['qa', 'chat', 'preference', 'roleplay', 'other']},
        {'name': 'evaluation_target', 'type': 'enum', 'allowed': ['elicitation', 'measurement', 'mitigation', 'mechanistic_analysis', 'other']},
        {'name': 'user_opinion_conditioned', 'type': 'boolean'},
        {'name': 'feedback_loop_involved', 'type': 'boolean'},
        {'name': 'llm_used', 'type': 'boolean'},
        {'name': 'benchmark_or_dataset', 'type': 'boolean'},
    ],
}

_HYBRID_FALLBACK_FIELDS: dict[str, set[str]] = {
    'multilingual-bias-benchmark-landscape': {'benchmark_name', 'human_evaluation_used', 'cross_lingual_comparison_present'},
    'conversational-summarization-landscape': {'evaluation_focus'},
    'sycophancy-evaluation-landscape': {'setup_type', 'benchmark_or_dataset', 'llm_used'},
}



def _normalize_string(value: Any) -> str:
    text = str(value or '').strip().lower()
    text = text.replace('-', '_').replace('/', '_')
    text = re.sub(r'[^a-z0-9_ ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text



def _fallback_model_name() -> str:
    return (
        os.environ.get('PAPER_SEARCH_REVIEW_EXTRACTION_MODEL', '').strip()
        or os.environ.get('OPENROUTER_REVIEW_EXTRACTION_MODEL', '').strip()
    )



def _should_use_fallback(project_id: str) -> bool:
    return project_id in _HYBRID_FALLBACK_SCHEMAS and bool(_fallback_model_name())



def _fallback_client() -> tuple[OpenAI, str] | None:
    model = _fallback_model_name()
    api_key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if not model or not api_key:
        return None
    return OpenAI(base_url='https://openrouter.ai/api/v1', api_key=api_key), model



def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError('Empty extraction output')
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r'\{.*\}', text, flags=re.S)
    if not match:
        raise ValueError('No JSON object found in extraction output')
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError('Extraction output must be a JSON object')
    return data



def _truthy_from_text(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _normalize_string(value)
    if text in {'true', 'yes', 'y', '1'}:
        return True
    if text in {'false', 'no', 'n', '0', '', 'null', 'none'}:
        return False
    if any(token in text for token in ['present', 'used', 'included']):
        return True
    if any(token in text for token in ['absent', 'unclear']):
        return False
    return None



def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else re.split(r'[,;/]|\band\b', str(value))
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip().strip('.,:;')
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out



def _enum_map(field: str, raw_value: Any, record: dict[str, Any], allowed: list[str]) -> str | None:
    text = _normalize_string(raw_value)
    evidence = _normalize_string(' '.join([str(raw_value or ''), record.get('title', ''), record.get('abstract', ''), record.get('summary', '')]))
    if not text or text in {'null', 'none', 'n_a', 'na', 'unknown', 'unclear'}:
        return None
    canonical = text.replace(' ', '_')
    if canonical in allowed:
        return canonical
    alias_maps = {
        'paper_type': {'systematic_review': 'survey', 'literature_review': 'survey', 'review': 'survey', 'research_paper': 'method', 'dataset': 'benchmark'},
        'benchmark_role': {'evaluation': 'uses_existing_benchmark', 'evaluator': 'uses_existing_benchmark', 'dataset': 'introduces_benchmark', 'benchmark': 'introduces_benchmark', 'comparison': 'compares_benchmarks', 'review': 'critique_of_benchmark'},
        'bias_type': {'multilingual_bias': 'cultural_bias', 'social_bias': 'cultural_bias', 'cultural': 'cultural_bias', 'stereotyping': 'stereotype', 'discrimination': 'stereotype', 'position_bias': 'positional_bias'},
        'dialogue_domain': {'virtual_meetings': 'meeting', 'medical_conversations': 'medical', 'clinical': 'medical', 'doctor_patient': 'medical', 'chat': 'open_domain_chat', 'conversation': 'open_domain_chat', 'dialogue': 'open_domain_chat'},
        'evaluation_focus': {'rouge_scores': 'summary_quality', 'rouge': 'summary_quality', 'factuality': 'faithfulness', 'hallucination': 'faithfulness', 'latency': 'efficiency', 'streaming': 'efficiency', 'preference': 'user_satisfaction'},
        'setup_type': {'dialogue': 'chat', 'assistant': 'chat', 'ranking': 'preference', 'rlhf': 'preference', 'persona': 'roleplay'},
        'evaluation_target': {'evaluation_framework': 'measurement', 'diagnostic': 'measurement', 'analysis': 'mechanistic_analysis', 'mechanistic': 'mechanistic_analysis', 'intervention': 'mitigation', 'debiasing': 'mitigation'},
        'language_scope': {'cross_lingual': 'cross_lingual', 'code_switching': 'code_switching', 'multilingual': 'multilingual', 'monolingual': 'monolingual'},
        'input_modality': {'asr': 'speech_or_transcript', 'audio': 'speech_or_transcript', 'spoken': 'speech_or_transcript', 'speech': 'speech_or_transcript', 'transcript': 'speech_or_transcript', 'video': 'multimodal', 'text': 'text_only'},
    }
    mapped = alias_maps.get(field, {}).get(canonical)
    if mapped in allowed:
        return mapped
    if field == 'paper_type':
        if any(token in evidence for token in ['survey', 'review', 'systematic review']):
            return 'survey' if 'survey' in allowed else None
        if any(token in evidence for token in ['benchmark', 'dataset', 'shared task', 'challenge']):
            return 'benchmark' if 'benchmark' in allowed else None
        if 'analysis' in allowed and any(token in evidence for token in ['analysis', 'mechanistic', 'probe']):
            return 'analysis'
        return 'method' if 'method' in allowed else None
    if field == 'benchmark_role':
        if any(token in evidence for token in ['compare', 'comparison']):
            return 'compares_benchmarks'
        if any(token in evidence for token in ['survey', 'review', 'critique']):
            return 'critique_of_benchmark'
        if any(token in evidence for token in ['introduce', 'propose', 'construct', 'curate', 'first']):
            return 'introduces_benchmark'
        return 'uses_existing_benchmark'
    if field == 'bias_type':
        if 'position' in evidence:
            return 'positional_bias'
        if 'stereotype' in evidence or 'stereotypical' in evidence or 'discrimination' in evidence:
            return 'stereotype'
        if 'toxic' in evidence:
            return 'toxicity'
        if 'fairness' in evidence:
            return 'fairness'
        if 'disparity' in evidence:
            return 'performance_disparity'
        if 'allocational' in evidence:
            return 'allocational_harm'
        if 'representational' in evidence:
            return 'representational_harm'
        if 'cultural' in evidence or 'multilingual' in evidence or 'chinese' in evidence or 'basque' in evidence or 'non english' in evidence:
            return 'cultural_bias'
        return 'other' if 'other' in allowed else None
    if field == 'dialogue_domain':
        if any(token in evidence for token in ['meeting', 'ami', 'icsi']):
            return 'meeting'
        if any(token in evidence for token in ['medical', 'clinical', 'doctor', 'patient']):
            return 'medical'
        if any(token in evidence for token in ['support', 'customer service']):
            return 'customer_support'
        if any(token in evidence for token in ['tweet', 'reddit', 'forum', 'social media']):
            return 'social_media'
        if any(token in evidence for token in ['chat', 'dialogue', 'conversation']):
            return 'open_domain_chat'
        return 'other'
    if field == 'evaluation_focus':
        if any(token in evidence for token in ['faithful', 'faithfulness', 'hallucination', 'factual']):
            return 'faithfulness'
        if any(token in evidence for token in ['preference', 'user satisfaction', 'helpfulness']):
            return 'user_satisfaction'
        if any(token in evidence for token in ['latency', 'efficiency', 'streaming', 'real time']):
            return 'efficiency'
        if any(token in evidence for token in ['rouge', 'bleu', 'summary quality', 'summarization quality']):
            return 'summary_quality'
        return 'other' if 'other' in allowed else None
    if field == 'setup_type':
        if any(token in evidence for token in ['multiple choice', 'question answering', 'qa']):
            return 'qa'
        if any(token in evidence for token in ['dialogue', 'chat', 'assistant', 'conversation']):
            return 'chat'
        if any(token in evidence for token in ['preference', 'ranking', 'rlhf', 'dpo']):
            return 'preference'
        if any(token in evidence for token in ['persona', 'roleplay']):
            return 'roleplay'
        return 'other'
    if field == 'evaluation_target':
        if 'mitigation' in allowed or 'mechanistic_analysis' in allowed:
            if any(token in evidence for token in ['mitigation', 'reduce', 'debias', 'intervention']):
                return 'mitigation' if 'mitigation' in allowed else None
            if any(token in evidence for token in ['mechanistic', 'probe', 'analysis', 'latent geometry']):
                return 'mechanistic_analysis' if 'mechanistic_analysis' in allowed else None
            if any(token in evidence for token in ['benchmark', 'dataset', 'measure', 'evaluation', 'framework']):
                return 'measurement' if 'measurement' in allowed else ('other' if 'other' in allowed else None)
            return 'elicitation' if 'elicitation' in allowed else ('other' if 'other' in allowed else None)
        if any(token in evidence for token in ['preference']):
            return 'preference' if 'preference' in allowed else None
        if any(token in evidence for token in ['rank', 'ranking']):
            return 'ranking' if 'ranking' in allowed else None
        if any(token in evidence for token in ['judge', 'llm judge']):
            return 'judge_based' if 'judge_based' in allowed else None
        if any(token in evidence for token in ['generat', 'generation', 'open ended']):
            return 'generative' if 'generative' in allowed else None
        if any(token in evidence for token in ['classification', 'multiple choice', 'qa', 'discriminat']):
            return 'discriminative' if 'discriminative' in allowed else None
        return None
    if field == 'language_scope':
        if 'cross lingual' in evidence or 'cross_lingual' in evidence:
            return 'cross_lingual'
        if 'code switching' in evidence or 'code_switching' in evidence:
            return 'code_switching'
        if any(token in evidence for token in ['multilingual', 'non english', 'beyond english']):
            return 'multilingual'
        return 'monolingual'
    if field == 'input_modality':
        if any(token in evidence for token in ['multimodal', 'video', 'vision language']):
            return 'multimodal'
        if any(token in evidence for token in ['speech', 'spoken', 'audio', 'asr', 'transcript']):
            return 'speech_or_transcript'
        return 'text_only'
    return None



def _normalize_fallback_value(field: dict[str, Any], raw_value: Any, record: dict[str, Any]) -> Any:
    kind = field['type']
    name = field['name']
    allowed = field.get('allowed') or []
    if kind == 'enum':
        value = _enum_map(name, raw_value, record, allowed)
        if value is None and 'other' in allowed:
            return 'other'
        return value
    if kind == 'boolean':
        value = _truthy_from_text(raw_value)
        return False if value is None else value
    if kind == 'integer':
        if raw_value in (None, '', 'null'):
            return None
        if isinstance(raw_value, int):
            return raw_value
        match = re.search(r'\d+', str(raw_value))
        return int(match.group(0)) if match else None
    if kind == 'list[text]':
        return _list_of_strings(raw_value)
    if name == 'benchmark_name':
        cleaned = _clean_benchmark_name(raw_value)
        if cleaned:
            return cleaned
        title_guess = _title_prefix_benchmark_name(str(record.get('title', '') or ''))
        if title_guess and any(token in _normalize_string(record.get('title', '')) for token in ['benchmark', 'dataset', 'bench']):
            return title_guess
        return None
    text = str(raw_value).strip() if raw_value is not None else ''
    return text or None



def _fallback_prompt(project, record: dict[str, Any]) -> str:
    schema = _HYBRID_FALLBACK_SCHEMAS[project.review_project_id]
    schema_text = '; '.join(
        f"{field['name']} ({field['type']}{'; allowed=' + str(field['allowed']) if field.get('allowed') else ''})"
        for field in schema
    )
    return (
        'You are extracting structured paper metadata for a literature review. '
        'Return exactly one valid JSON object. No markdown. No explanation.\n\n'
        f'Project: {project.review_project_id}\n'
        f'Schema: {schema_text}\n\n'
        f"Paper title: {record.get('title', '')}\n"
        f"Abstract: {record.get('abstract', '') or 'N/A'}\n"
        f"Summary: {record.get('summary', '') or 'N/A'}\n"
        f"Chinese brief: {record.get('zh_brief', '') or 'N/A'}\n\n"
        'Rules:\n'
        '1. Use exactly these keys and no others.\n'
        '2. For enum fields, output only one allowed value.\n'
        '3. For booleans, output true or false.\n'
        '4. For list[text], output a JSON array of strings.\n'
        '5. For integer, output an integer or null.\n'
        '6. For text fields, output a short string or null.\n'
        '7. If evidence is missing, use null for nullable scalar fields, false for unsupported boolean claims, and [] for list fields.\n'
        '8. Prefer schema validity over creativity.'
    )



def _llm_fallback_extract(project, record: dict[str, Any], max_retries: int = 3) -> dict[str, Any]:
    client_info = _fallback_client()
    if client_info is None:
        return {}
    client, model = client_info
    prompt = _fallback_prompt(project, record)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=500,
                temperature=0,
            )
            text = (response.choices[0].message.content or '').strip() if response.choices else ''
            raw = _extract_json_object(text)
            normalized: dict[str, Any] = {}
            for field in _HYBRID_FALLBACK_SCHEMAS[project.review_project_id]:
                normalized[field['name']] = _normalize_fallback_value(field, raw.get(field['name']), record)
            return normalized
        except Exception as exc:
            last_error = exc
            if '429' in str(exc) and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
                continue
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
    return {}



def _merge_hybrid_extraction(project_id: str, heuristic: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not fallback:
        return heuristic
    merged = dict(heuristic)
    preferred = _HYBRID_FALLBACK_FIELDS.get(project_id, set())
    for key, value in fallback.items():
        if value in (None, [], ''):
            continue
        if key in preferred or merged.get(key) in (None, '', [], False):
            merged[key] = value
    return merged



def _extraction_messages(project, record: dict[str, Any], model: str) -> list[dict[str, str]]:
    prompt = f"""
You are extracting structured fields for a review project.

Review project: {project.review_project_name}
Objective: {project.objective}
Research questions:
""".strip()
    prompt += "\n" + "\n".join(f"- {q}" for q in project.research_questions)
    prompt += (
        f"\n\nPaper title: {record.get('title', '')}"
        f"\nScreening rationale: {record.get('screening_rationale', '') or 'N/A'}"
        f"\nPaper abstract: {record.get('abstract', '') or 'N/A'}"
        f"\nPaper summary: {record.get('summary', '') or 'N/A'}"
        f"\nChinese brief: {record.get('zh_brief', '') or 'N/A'}"
        f"\nPaper limitations: {record.get('paper_limitations', []) or 'N/A'}"
        "\n\nExtract a JSON object with these fields:\n"
        f"{_schema_summary(project)}\n"
        "Return strict JSON only. Use only provided evidence. If unsure, use null or an empty list."
    )
    if "gemma" in model.lower():
        return [{"role": "user", "content": prompt}]
    return [
        {"role": "system", "content": "You are a careful literature review extractor. Return strict JSON only."},
        {"role": "user", "content": prompt},
    ]


def _fast_extract_multilingual_bias(record: dict[str, Any]) -> dict[str, Any]:
    text = ' '.join(str(record.get(k, '') or '') for k in ('title', 'abstract', 'summary', 'zh_brief')).lower()

    benchmark_name = None
    for pat in [r'([a-z0-9-]*bbq[a-z0-9-]*)', r'([a-z0-9-]*bench[a-z0-9-]*)']:
        m = re.search(pat, text)
        if m:
            benchmark_name = _clean_benchmark_name(m.group(1))
            break
    if 'dataset' in text and benchmark_name is None:
        title = str(record.get('title', '')).strip()
        benchmark_name = _title_prefix_benchmark_name(title)

    if benchmark_name is not None or 'introduce' in text or 'dataset' in text or 'benchmark' in text:
        benchmark_role = 'introduces_benchmark'
    elif 'systematic review' in text or 'survey' in text or 'review' in text:
        benchmark_role = 'critique_of_benchmark'
    else:
        benchmark_role = 'uses_existing_benchmark'

    bias_type = 'other'
    if 'position bias' in text or 'positional bias' in text:
        bias_type = 'positional_bias'
    elif any(token in text for token in ['cultural', 'culture ', 'geo-cultural', 'geocultural', 'cross-cultural']):
        bias_type = 'cultural_bias'
    elif any(token in text for token in ['stereotype', 'stereotypical', 'gender bias', 'racial bias', 'political bias', 'religious bias', 'sexist', 'homophobic', 'colorism']):
        bias_type = 'stereotype'
    elif 'toxicity' in text or 'toxic' in text:
        bias_type = 'toxicity'
    elif 'fairness' in text:
        bias_type = 'fairness'
    elif any(token in text for token in ['disparity', 'performance gap', 'performance gaps', 'dialect fairness', 'robustness disparities']):
        bias_type = 'performance_disparity'
    elif 'allocational harm' in text:
        bias_type = 'allocational_harm'
    elif 'representational harm' in text:
        bias_type = 'representational_harm'

    languages = []
    for lang in [
        'basque','french','arabic','spanish','chinese','mandarin','cantonese','hindi','english','korean','japanese','german',
        'bangla','bengali','turkish','maltese','catalan','czech','italian','persian','amharic','vietnamese','indic',
        'west slavic','traditional chinese','simplified chinese','taiwan',
    ]:
        if re.search(r'\b' + re.escape(lang) + r'\b', text):
            languages.append(lang)
    explicit_language_count = len(set(languages))
    count_match = re.search(r'(\d{1,3})\s+(?:language|languages|language variants)', text)
    mention_count = int(count_match.group(1)) if count_match else None
    if 'cross-lingual' in text or 'cross lingual' in text:
        language_scope = 'cross_lingual'
    elif any(token in text for token in ['multilingual', 'beyond english', 'non-english', 'across languages', 'many languages', 'language variants']) or explicit_language_count > 1 or (mention_count and mention_count > 1):
        language_scope = 'multilingual'
    else:
        language_scope = 'monolingual'
    language_count = mention_count or explicit_language_count or None
    if language_scope == 'monolingual' and (language_count or 0) > 1:
        language_scope = 'multilingual'
    if language_scope in {'multilingual', 'cross_lingual'} and language_count == 1:
        language_count = None

    translation_based = any(x in text for x in ['translation', 'translated'])
    native_authored_data = any(x in text for x in ['native-authored', 'natively authored', 'native data'])
    human_evaluation_used = 'human evaluation' in text or 'human annot' in text
    cross_lingual_comparison_present = 'cross-lingual' in text or 'across languages' in text or 'beyond english' in text

    if 'french' in text:
        rel_french = 'high'
    else:
        rel_french = 'medium' if language_scope == 'multilingual' else 'low'
    rel_unified = 'high' if language_scope == 'multilingual' else 'low'

    gap_tags = []
    for phrase, tag in [
        ('anglocentric', 'Anglocentric bias'),
        ('translation', 'translation-based dataset construction'),
        ('cultural context', 'cultural context neglect'),
        ('benchmark scarcity', 'benchmark scarcity'),
        ('generalize', 'safety generalization failure'),
    ]:
        if phrase in text:
            gap_tags.append(tag)

    return {
        'paper_type': 'survey' if benchmark_role == 'critique_of_benchmark' else 'benchmark',
        'bias_type': bias_type,
        'benchmark_name': benchmark_name,
        'benchmark_role': benchmark_role,
        'language_scope': language_scope,
        'languages': sorted(set(languages)),
        'language_count': language_count,
        'translation_based': translation_based,
        'native_authored_data': native_authored_data,
        'protected_attributes': [],
        'evaluation_target': None,
        'human_evaluation_used': human_evaluation_used,
        'cross_lingual_comparison_present': cross_lingual_comparison_present,
        'relevance_to_frenchbbq': rel_french,
        'relevance_to_multilingual_unified_bbq': rel_unified,
        'review_gap_tags': gap_tags,
    }


def _fast_extract_conv_summarization(record: dict[str, Any]) -> dict[str, Any]:
    text = ' '.join(str(record.get(k, '') or '') for k in ('title', 'abstract', 'summary', 'zh_brief')).lower()
    title = str(record.get('title', '')).strip()

    benchmark_name = None
    for token in ['dialogsum', 'samsum', 'qmsum', 'meetingbank', 'mediasum', 'tweetsumm']:
        if token in text:
            benchmark_name = _clean_benchmark_name(token)
            break
    if benchmark_name is None and any(x in text for x in ['dataset', 'benchmark', 'shared task', 'challenge']):
        benchmark_name = _title_prefix_benchmark_name(title)

    if benchmark_name is not None or any(x in text for x in ['dataset', 'benchmark', 'shared task', 'challenge']):
        paper_type = 'benchmark'
    elif any(x in text for x in ['survey', 'review']):
        paper_type = 'survey'
    else:
        paper_type = 'method'

    if any(x in text for x in ['meeting', 'meetingbank', 'ami', 'icsi']):
        dialogue_domain = 'meeting'
    elif any(x in text for x in ['customer service', 'support chat']):
        dialogue_domain = 'customer_support'
    elif any(x in text for x in ['medical', 'clinical', 'doctor-patient']):
        dialogue_domain = 'medical'
    elif any(x in text for x in ['social media', 'tweet', 'forum', 'reddit']):
        dialogue_domain = 'social_media'
    elif any(x in text for x in ['chat', 'dialogue', 'conversation']):
        dialogue_domain = 'open_domain_chat'
    else:
        dialogue_domain = 'other'

    if any(x in text for x in ['multimodal', 'video', 'vision-language']):
        input_modality = 'multimodal'
    elif any(x in text for x in ['speech', 'spoken', 'audio', 'asr', 'transcript']):
        input_modality = 'speech_or_transcript'
    else:
        input_modality = 'text_only'

    if any(x in text for x in ['faithful', 'faithfulness', 'hallucination', 'factuality']):
        evaluation_focus = 'faithfulness'
    elif any(x in text for x in ['user satisfaction', 'helpfulness', 'preference']):
        evaluation_focus = 'user_satisfaction'
    elif any(x in text for x in ['efficiency', 'latency', 'streaming', 'real-time']):
        evaluation_focus = 'efficiency'
    else:
        evaluation_focus = 'summary_quality'

    llm_used = any(x in text for x in ['large language model', 'llm', 'gpt', 'chatgpt'])
    multilingual_or_crosslingual = any(x in text for x in ['multilingual', 'cross-lingual', 'cross lingual'])
    streaming_or_real_time = any(x in text for x in ['streaming', 'real-time', 'online summarization'])

    gap_tags = []
    for phrase, tag in [
        ('faithful', 'faithfulness underexplored'),
        ('spoken', 'spoken dialogue noise and ASR error sensitivity'),
        ('multilingual', 'limited multilingual conversational summarization coverage'),
        ('streaming', 'real-time summarization constraints'),
        ('human evaluation', 'evaluation mismatch between automatic and human judgment'),
    ]:
        if phrase in text:
            gap_tags.append(tag)

    return {
        'paper_type': paper_type,
        'benchmark_name': benchmark_name,
        'dialogue_domain': dialogue_domain,
        'input_modality': input_modality,
        'evaluation_focus': evaluation_focus,
        'llm_used': llm_used,
        'multilingual_or_crosslingual': multilingual_or_crosslingual,
        'streaming_or_real_time': streaming_or_real_time,
        'relevance_to_conversational_summarization_work': 'high',
        'review_gap_tags': gap_tags,
    }


def _fast_extract_sycophancy(record: dict[str, Any]) -> dict[str, Any]:
    text = ' '.join(str(record.get(k, '') or '') for k in ('title', 'abstract', 'summary', 'zh_brief')).lower()
    title = str(record.get('title', '')).strip()

    benchmark_name = None
    if any(x in text for x in ['benchmark', 'dataset', 'eval']):
        benchmark_name = _title_prefix_benchmark_name(title)

    if benchmark_name is not None or any(x in text for x in ['benchmark', 'dataset']):
        paper_type = 'benchmark'
    elif any(x in text for x in ['survey', 'review']):
        paper_type = 'survey'
    elif any(x in text for x in ['analysis', 'probe', 'mechanistic']):
        paper_type = 'analysis'
    else:
        paper_type = 'method'

    if any(x in text for x in ['multiple-choice', 'qa', 'question answering']):
        setup_type = 'qa'
    elif any(x in text for x in ['chatbot', 'conversation', 'dialogue', 'assistant']):
        setup_type = 'chat'
    elif any(x in text for x in ['preference', 'ranking', 'rlhf']):
        setup_type = 'preference'
    elif any(x in text for x in ['roleplay', 'persona']):
        setup_type = 'roleplay'
    else:
        setup_type = 'other'

    if any(x in text for x in ['mitigation', 'reduce sycophancy', 'intervention']):
        evaluation_target = 'mitigation'
    elif any(x in text for x in ['mechanistic', 'probe', 'analysis', 'why']):
        evaluation_target = 'mechanistic_analysis'
    elif any(x in text for x in ['benchmark', 'dataset', 'measure', 'evaluation']):
        evaluation_target = 'measurement'
    else:
        evaluation_target = 'elicitation'

    user_opinion_conditioned = any(x in text for x in ['user belief', 'user-belief', 'user opinion', 'agree with the user', 'opinion mirroring'])
    feedback_loop_involved = any(x in text for x in ['rlhf', 'reward model', 'preference optimization', 'reward hacking', 'alignment faking'])
    llm_used = any(x in text for x in ['large language model', 'llm', 'gpt', 'chatgpt'])
    benchmark_or_dataset = any(x in text for x in ['benchmark', 'dataset'])

    gap_tags = []
    for phrase, tag in [
        ('rlhf', 'RLHF-induced sycophancy mechanism'),
        ('benchmark', 'lack of standardized sycophancy benchmarks'),
        ('mitigation', 'robust mitigation remains limited'),
        ('user belief', 'user-opinion conditioning realism'),
        ('alignment faking', 'boundary between sycophancy and alignment faking'),
    ]:
        if phrase in text:
            gap_tags.append(tag)

    return {
        'paper_type': paper_type,
        'benchmark_name': benchmark_name,
        'setup_type': setup_type,
        'evaluation_target': evaluation_target,
        'user_opinion_conditioned': user_opinion_conditioned,
        'feedback_loop_involved': feedback_loop_involved,
        'llm_used': llm_used,
        'benchmark_or_dataset': benchmark_or_dataset,
        'relevance_to_sycophancy_work': 'high',
        'review_gap_tags': gap_tags,
    }


def extract_record(project, record: dict[str, Any], max_retries: int = 3) -> dict[str, Any]:
    cached = get_cached_review_extraction(project.review_project_id, record)
    if project.review_project_id == 'multilingual-bias-benchmark-landscape':
        heuristic = _fast_extract_multilingual_bias(record)
        if cached:
            return _merge_hybrid_extraction(project.review_project_id, heuristic, cached)
        if _should_use_fallback(project.review_project_id):
            return _merge_hybrid_extraction(project.review_project_id, heuristic, _llm_fallback_extract(project, record, max_retries=max_retries))
        return heuristic
    if project.review_project_id == 'conversational-summarization-landscape':
        heuristic = _fast_extract_conv_summarization(record)
        if cached:
            return _merge_hybrid_extraction(project.review_project_id, heuristic, cached)
        if _should_use_fallback(project.review_project_id):
            return _merge_hybrid_extraction(project.review_project_id, heuristic, _llm_fallback_extract(project, record, max_retries=max_retries))
        return heuristic
    if project.review_project_id == 'sycophancy-evaluation-landscape':
        heuristic = _fast_extract_sycophancy(record)
        if cached:
            return _merge_hybrid_extraction(project.review_project_id, heuristic, cached)
        if _should_use_fallback(project.review_project_id):
            return _merge_hybrid_extraction(project.review_project_id, heuristic, _llm_fallback_extract(project, record, max_retries=max_retries))
        return heuristic

    if cached:
        return cached

    client, model = get_llm_client()
    messages = _extraction_messages(project, record, model)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=900,
                temperature=0.1,
            )
            text = (response.choices[0].message.content or "").strip() if response.choices else ""
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("Extraction output must be a JSON object")
            return data
        except Exception as e:
            last_error = e
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 5)
                continue
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            raise last_error
    raise last_error or RuntimeError("extraction failed")


def build_extraction_row(project, record: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    row["extraction"] = extraction
    row["review_status"] = "extracted"
    row["extracted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return row
