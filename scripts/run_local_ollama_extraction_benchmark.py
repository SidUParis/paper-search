from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any

MODEL = 'qwen2.5:3b'
OLLAMA_URL = 'http://127.0.0.1:11434/api/generate'
SAMPLE_PATH = Path('/home/orange/paper-search/cache/local_benchmark_sample.json')
OUT_PATH = Path('/home/orange/paper-search/cache/local_benchmark_results.json')

SCHEMAS: dict[str, dict[str, Any]] = {
    'multilingual-bias-benchmark-landscape': {
        'description': 'Multilingual bias benchmark review extraction',
        'fields': [
            {'name': 'paper_type', 'type': 'enum', 'allowed': ['benchmark', 'survey']},
            {
                'name': 'benchmark_role',
                'type': 'enum',
                'allowed': ['introduces_benchmark', 'uses_existing_benchmark', 'compares_benchmarks', 'critique_of_benchmark'],
            },
            {'name': 'benchmark_name', 'type': 'text'},
            {
                'name': 'bias_type',
                'type': 'enum',
                'allowed': [
                    'stereotype',
                    'toxicity',
                    'fairness',
                    'cultural_bias',
                    'performance_disparity',
                    'positional_bias',
                    'allocational_harm',
                    'representational_harm',
                    'other',
                ],
            },
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
    },
    'conversational-summarization-landscape': {
        'description': 'Conversational summarization review extraction',
        'fields': [
            {'name': 'paper_type', 'type': 'enum', 'allowed': ['benchmark', 'survey', 'method']},
            {'name': 'benchmark_name', 'type': 'text'},
            {'name': 'dialogue_domain', 'type': 'enum', 'allowed': ['meeting', 'customer_support', 'medical', 'social_media', 'open_domain_chat', 'other']},
            {'name': 'input_modality', 'type': 'enum', 'allowed': ['text_only', 'speech_or_transcript', 'multimodal']},
            {'name': 'evaluation_focus', 'type': 'enum', 'allowed': ['summary_quality', 'faithfulness', 'user_satisfaction', 'efficiency', 'other']},
            {'name': 'llm_used', 'type': 'boolean'},
            {'name': 'multilingual_or_crosslingual', 'type': 'boolean'},
            {'name': 'streaming_or_real_time', 'type': 'boolean'},
        ],
    },
    'sycophancy-evaluation-landscape': {
        'description': 'Sycophancy evaluation review extraction',
        'fields': [
            {'name': 'paper_type', 'type': 'enum', 'allowed': ['benchmark', 'survey', 'analysis', 'method']},
            {'name': 'benchmark_name', 'type': 'text'},
            {'name': 'setup_type', 'type': 'enum', 'allowed': ['qa', 'chat', 'preference', 'roleplay', 'other']},
            {'name': 'evaluation_target', 'type': 'enum', 'allowed': ['elicitation', 'measurement', 'mitigation', 'mechanistic_analysis', 'other']},
            {'name': 'user_opinion_conditioned', 'type': 'boolean'},
            {'name': 'feedback_loop_involved', 'type': 'boolean'},
            {'name': 'llm_used', 'type': 'boolean'},
            {'name': 'benchmark_or_dataset', 'type': 'boolean'},
        ],
    },
}

PROMPT_TEMPLATE = '''You are extracting structured paper metadata for a literature review.
Return exactly one valid JSON object. No markdown. No explanation.

Project: {project_id}
Schema: {schema_description}

Paper title: {title}
Abstract: {abstract}
Summary: {summary}

Rules:
1. Use exactly these keys and no others.
2. For enum fields, output only one allowed value.
3. For booleans, output true or false.
4. For list[text], output a JSON array of strings.
5. For integer, output an integer or null.
6. For text fields, output a short string or null.
7. If evidence is missing, use null for nullable scalar fields, false for unsupported boolean claims, and [] for list fields.
8. Prefer schema validity over creativity.
'''


def _schema_description(project_id: str) -> str:
    spec = SCHEMAS[project_id]
    parts = []
    for field in spec['fields']:
        field_type = field['type']
        allowed = field.get('allowed')
        if allowed:
            parts.append(f"{field['name']} ({field_type}; allowed={allowed})")
        else:
            parts.append(f"{field['name']} ({field_type})")
    return '; '.join(parts)


def ollama_generate(prompt: str) -> str:
    payload = json.dumps(
        {
            'model': MODEL,
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            'options': {
                'temperature': 0,
                'num_ctx': 4096,
            },
        }
    ).encode('utf-8')
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=240) as resp:
        body = json.loads(resp.read().decode('utf-8'))
    return body['response']


def _normalize_string(value: Any) -> str:
    text = str(value or '').strip().lower()
    text = text.replace('-', '_').replace('/', '_')
    text = re.sub(r'[^a-z0-9_ ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _clean_benchmark_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip('.,:;()[]{}')
    if not text:
        return None
    if ':' in text:
        prefix = text.split(':', 1)[0].strip()
        if prefix and len(prefix.split()) <= 6:
            text = prefix
    lowered = text.lower()
    lowered = re.sub(r'\b(qa )?benchmark\b.*$', '', lowered).strip()
    lowered = re.sub(r'\bdataset\b.*$', '', lowered).strip()
    lowered = re.sub(r'\bevaluation framework\b.*$', '', lowered).strip()
    lowered = lowered.strip(' -_:;,.')
    if not lowered:
        return None
    if lowered in {'benchmark', 'dataset', 'review', 'survey', 'evaluation', 'framework'}:
        return None
    return lowered


def _title_prefix_benchmark_name(title: str) -> str | None:
    if ':' not in title:
        return None
    prefix = title.split(':', 1)[0].strip()
    if not prefix or len(prefix.split()) > 6:
        return None
    return _clean_benchmark_name(prefix)


def _truthy_from_text(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _normalize_string(value)
    if text in {'true', 'yes', 'y', '1'}:
        return True
    if text in {'false', 'no', 'n', '0', '', 'null', 'none'}:
        return False
    if any(token in text for token in ['yes', 'true', 'present', 'used', 'included']):
        return True
    if any(token in text for token in ['no', 'not ', 'none', 'absent', 'unclear']):
        return False
    return None


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r'[,;/]|\band\b', str(value))
    cleaned = []
    seen = set()
    for item in raw_items:
        text = str(item).strip().strip('.,:;')
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r'\{.*\}', text, flags=re.S)
    if not match:
        raise ValueError('No JSON object found in model output')
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError('Model output JSON is not an object')
    return data


def _enum_map(field: str, raw_value: Any, record: dict[str, Any], allowed: list[str]) -> str | None:
    text = _normalize_string(raw_value)
    evidence = _normalize_string(' '.join([str(raw_value or ''), record.get('title', ''), record.get('abstract', ''), record.get('summary', '')]))
    if not text or text in {'null', 'none', 'n_a', 'na', 'unknown', 'unclear'}:
        return None
    canonical = text.replace(' ', '_')
    if canonical in allowed:
        return canonical

    alias_maps = {
        'paper_type': {
            'systematic_review': 'survey',
            'literature_review': 'survey',
            'review': 'survey',
            'research_paper': 'method',
            'model_paper': 'method',
            'evaluation_framework': 'benchmark',
            'dataset': 'benchmark',
            'benchmark_dataset': 'benchmark',
        },
        'benchmark_role': {
            'evaluation': 'uses_existing_benchmark',
            'evaluator': 'uses_existing_benchmark',
            'dataset': 'introduces_benchmark',
            'benchmark': 'introduces_benchmark',
            'comparison': 'compares_benchmarks',
            'review': 'critique_of_benchmark',
        },
        'bias_type': {
            'multilingual_bias': 'cultural_bias',
            'social_bias': 'cultural_bias',
            'cultural': 'cultural_bias',
            'stereotyping': 'stereotype',
            'discrimination': 'stereotype',
            'stereotyping_discrimination': 'stereotype',
            'position_bias': 'positional_bias',
        },
        'dialogue_domain': {
            'virtual_meetings': 'meeting',
            'meeting_dialogue': 'meeting',
            'medical_conversations': 'medical',
            'clinical': 'medical',
            'doctor_patient': 'medical',
            'tweets': 'social_media',
            'forums': 'social_media',
            'reddit': 'social_media',
            'chat': 'open_domain_chat',
            'conversation': 'open_domain_chat',
            'dialogue': 'open_domain_chat',
        },
        'evaluation_focus': {
            'rouge_scores': 'summary_quality',
            'rouge': 'summary_quality',
            'bleu': 'summary_quality',
            'quality': 'summary_quality',
            'factuality': 'faithfulness',
            'hallucination': 'faithfulness',
            'latency': 'efficiency',
            'real_time': 'efficiency',
            'streaming': 'efficiency',
            'preference': 'user_satisfaction',
            'helpfulness': 'user_satisfaction',
        },
        'setup_type': {
            'multi_turn_dialogues': 'chat',
            'dialogue': 'chat',
            'assistant': 'chat',
            'ranking': 'preference',
            'rlhf': 'preference',
            'persona': 'roleplay',
        },
        'evaluation_target': {
            'evaluation_framework': 'measurement',
            'evaluator': 'measurement',
            'diagnostic': 'measurement',
            'analysis': 'mechanistic_analysis',
            'mechanistic': 'mechanistic_analysis',
            'probe': 'mechanistic_analysis',
            'intervention': 'mitigation',
            'debiasing': 'mitigation',
            'measurement': 'measurement',
        },
        'language_scope': {
            'cross_lingual': 'cross_lingual',
            'cross lingual': 'cross_lingual',
            'code switching': 'code_switching',
            'multilingual': 'multilingual',
            'monolingual': 'monolingual',
        },
        'input_modality': {
            'asr': 'speech_or_transcript',
            'audio': 'speech_or_transcript',
            'spoken': 'speech_or_transcript',
            'speech': 'speech_or_transcript',
            'transcript': 'speech_or_transcript',
            'video': 'multimodal',
            'vision_language': 'multimodal',
            'text': 'text_only',
        },
    }
    alias = alias_maps.get(field, {}).get(canonical)
    if alias in allowed:
        return alias

    if field == 'paper_type':
        if any(token in evidence for token in ['survey', 'review', 'systematic review', 'literature review']):
            return 'survey' if 'survey' in allowed else None
        if any(token in evidence for token in ['benchmark', 'dataset', 'shared task', 'challenge']):
            return 'benchmark' if 'benchmark' in allowed else None
        if 'analysis' in allowed and any(token in evidence for token in ['analysis', 'mechanistic', 'probe', 'diagnostic']):
            return 'analysis'
        if 'method' in allowed:
            return 'method'

    if field == 'benchmark_role':
        if any(token in evidence for token in ['compare', 'comparison', 'across benchmarks']):
            return 'compares_benchmarks'
        if any(token in evidence for token in ['survey', 'review', 'critique']):
            return 'critique_of_benchmark'
        if any(token in evidence for token in ['introduce', 'we introduce', 'propose', 'construct', 'curate', 'first']):
            return 'introduces_benchmark'
        if any(token in evidence for token in ['evaluate', 'using', 'on bbq', 'on samsum', 'on qmsum']):
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
        if 'bias' in evidence:
            return 'other' if 'other' in allowed else None
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
        if any(token in evidence for token in ['judge', 'judge based', 'llm judge']):
            return 'judge_based' if 'judge_based' in allowed else None
        if any(token in evidence for token in ['generat', 'generation', 'open ended', 'text generation']):
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


def _normalize_value(field: dict[str, Any], raw_value: Any, record: dict[str, Any]) -> Any:
    name = field['name']
    kind = field['type']
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

    if kind == 'text':
        if name == 'benchmark_name':
            cleaned = _clean_benchmark_name(raw_value)
            if cleaned:
                return cleaned
            title_guess = _title_prefix_benchmark_name(record.get('title', ''))
            if title_guess and any(token in _normalize_string(record.get('title', '')) for token in ['benchmark', 'dataset', 'bench']):
                return title_guess
            return None
        text = str(raw_value).strip() if raw_value is not None else ''
        return text or None

    return raw_value


def _compare_values(left: Any, right: Any) -> bool:
    if isinstance(left, list) and isinstance(right, list):
        return sorted(str(x).lower() for x in left) == sorted(str(x).lower() for x in right)
    return left == right


def _project_summary_bucket() -> dict[str, Any]:
    return {
        'items': 0,
        'raw_parse_errors': 0,
        'all_fields_match': 0,
        'field_matches': {},
        'field_totals': {},
    }


def main() -> None:
    sample = json.loads(SAMPLE_PATH.read_text(encoding='utf-8'))
    items = []
    summary = {
        'model': MODEL,
        'sample_size': len(sample),
        'overall': _project_summary_bucket(),
        'by_project': {project_id: _project_summary_bucket() for project_id in SCHEMAS},
    }

    for item in sample:
        project_id = item['project_id']
        schema = SCHEMAS[project_id]
        prompt = PROMPT_TEMPLATE.format(
            project_id=project_id,
            schema_description=_schema_description(project_id),
            title=item['title'],
            abstract=item.get('abstract', ''),
            summary=item.get('summary', ''),
        )
        heuristic = item.get('heuristic_extraction', {})
        raw_parsed = {}
        normalized = {}
        field_matches = {}
        parse_error = None

        try:
            text = ollama_generate(prompt)
            raw_parsed = _extract_json_object(text)
        except Exception as exc:
            parse_error = str(exc)
            text = ''

        for field in schema['fields']:
            normalized[field['name']] = _normalize_value(field, raw_parsed.get(field['name']), item)

        bucket = summary['by_project'][project_id]
        overall = summary['overall']
        bucket['items'] += 1
        overall['items'] += 1

        if parse_error:
            bucket['raw_parse_errors'] += 1
            overall['raw_parse_errors'] += 1

        all_match = True
        compared = 0
        for field in schema['fields']:
            name = field['name']
            if name not in heuristic:
                continue
            compared += 1
            match = _compare_values(normalized.get(name), heuristic.get(name))
            field_matches[name] = match
            if not match:
                all_match = False
            bucket['field_totals'][name] = bucket['field_totals'].get(name, 0) + 1
            overall['field_totals'][name] = overall['field_totals'].get(name, 0) + 1
            if match:
                bucket['field_matches'][name] = bucket['field_matches'].get(name, 0) + 1
                overall['field_matches'][name] = overall['field_matches'].get(name, 0) + 1

        if compared and all_match:
            bucket['all_fields_match'] += 1
            overall['all_fields_match'] += 1

        items.append(
            {
                'project_id': project_id,
                'title': item['title'],
                'heuristic_extraction': heuristic,
                'raw_local_model_extraction': raw_parsed,
                'normalized_local_model_extraction': normalized,
                'field_matches_vs_heuristics': field_matches,
                'parse_error': parse_error,
                'raw_response_text': text,
            }
        )
        status = 'OK' if not parse_error else 'ERR'
        print(status, project_id, item['title'][:80])

    for bucket in [summary['overall'], *summary['by_project'].values()]:
        bucket['field_match_rates'] = {
            name: round(bucket['field_matches'].get(name, 0) / total, 3)
            for name, total in bucket['field_totals'].items()
            if total
        }
        bucket['all_fields_match_rate'] = round(bucket['all_fields_match'] / bucket['items'], 3) if bucket['items'] else 0.0
        bucket['raw_parse_error_rate'] = round(bucket['raw_parse_errors'] / bucket['items'], 3) if bucket['items'] else 0.0

    OUT_PATH.write_text(
        json.dumps({'summary': summary, 'items': items}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(str(OUT_PATH))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
