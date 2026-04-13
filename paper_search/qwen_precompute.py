"""Qwen CLI-based precompute cache and helpers.

This module is intentionally non-invasive: callers can read precomputed outputs
first and fall back to the current OpenRouter workflow when cache is missing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from textwrap import dedent
from typing import Any

ROOT_DIR = Path(os.path.dirname(os.path.dirname(__file__)))
QWEN_PRECOMPUTE_DIR = ROOT_DIR / "cache" / "qwen_precompute"
QWEN_PRECOMPUTE_STATE = QWEN_PRECOMPUTE_DIR / "state.json"
QWEN_TMP_OUTPUT_DIR = QWEN_PRECOMPUTE_DIR / "tmp"
DEFAULT_QWEN_COMMAND = os.environ.get("PAPER_SEARCH_QWEN_COMMAND", "qwen")
PROMPT_VERSION = "fairness-qwen-precompute-v1"
DEFAULT_QWEN_MAX_INPUT_CHARS = int(os.environ.get("PAPER_SEARCH_QWEN_MAX_INPUT_CHARS", "28000"))

_SHARED_SYSTEM_PROMPT = dedent(
    """
    You are a careful research extraction assistant for AI fairness, AI bias, multilingual evaluation, and benchmark design.

    Rules:
    1. Use only the supplied paper text and metadata.
    2. Do not invent claims, results, datasets, languages, baselines, or limitations.
    3. If information is missing, write "not stated".
    4. If the evidence is weak or ambiguous, write "unclear from provided text".
    5. Prefer precise, compact wording over broad interpretation.
    6. Preserve benchmark names, dataset names, model names, language names, and metrics exactly when possible.
    7. Return valid JSON only with no markdown fences or extra commentary.
    8. Prioritize usefulness for FrenchBBQ, multilingual unified BBQ, and LLM bias/fairness evaluation research.
    """
).strip()


def _ensure_dirs() -> None:
    QWEN_PRECOMPUTE_DIR.mkdir(parents=True, exist_ok=True)
    QWEN_TMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _fallback_key(paper_id: str) -> str:
    return hashlib.sha256(paper_id.strip().encode("utf-8")).hexdigest()[:24]


def cache_key(*, source_url: str = "", paper_id: str = "") -> str:
    if source_url.strip():
        return hashlib.sha256(source_url.strip().encode("utf-8")).hexdigest()[:24]
    if paper_id.strip():
        return _fallback_key(paper_id)
    raise ValueError("source_url or paper_id required")


def cache_path(*, source_url: str = "", paper_id: str = "") -> Path:
    _ensure_dirs()
    return QWEN_PRECOMPUTE_DIR / f"{cache_key(source_url=source_url, paper_id=paper_id)}.json"


def load_precompute(*, source_url: str = "", paper_id: str = "") -> dict[str, Any] | None:
    if not str(source_url or "").strip() and not str(paper_id or "").strip():
        return None
    path = cache_path(source_url=source_url, paper_id=paper_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def save_precompute(payload: dict[str, Any], *, source_url: str = "", paper_id: str = "") -> Path:
    path = cache_path(source_url=source_url, paper_id=paper_id)
    payload = dict(payload)
    payload.setdefault("prompt_version", PROMPT_VERSION)
    payload.setdefault("updated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_state() -> dict[str, Any]:
    _ensure_dirs()
    if not QWEN_PRECOMPUTE_STATE.exists():
        return {"done_keys": [], "updated_at": None}
    try:
        data = json.loads(QWEN_PRECOMPUTE_STATE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("done_keys", [])
            return data
    except Exception:
        pass
    return {"done_keys": [], "updated_at": None}


def save_state(state: dict[str, Any]) -> None:
    _ensure_dirs()
    state = dict(state)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    QWEN_PRECOMPUTE_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_summary_prompt(*, paper_id: str, title: str, year: str | int | None, venue: str, paper_text: str) -> str:
    return dedent(
        f"""
        {_SHARED_SYSTEM_PROMPT}

        Task: Produce a concise but research-useful summary bundle for downstream Obsidian / Notion workflows in AI fairness, AI bias, multilingual evaluation, and benchmark design.

        Metadata:
        - paper_id: {paper_id}
        - title: {title}
        - year: {year or 'not stated'}
        - venue: {venue or 'not stated'}

        Style requirements:
        - Be useful for a researcher working on FrenchBBQ, multilingual unified BBQ, and LLM evaluation.
        - Prioritize benchmark design, language coverage, protected groups, evaluation protocol, and what can be reused.
        - Keep the English summary compact and skimmable.
        - The Chinese brief must sound natural and oral, not like literal translation.
        - Do not write generic praise or vague claims.
        - If information is missing, write 'not stated'.

        Return JSON with exactly these keys:
        {{
          "summary": "English markdown with sections ## RQ, ## Idea, ## Method, ## Theory, ## Results. Total about 180-260 words. Emphasize benchmark/setup/results rather than background.",
          "zh_brief": "Natural Chinese research brief in 4-6 sentences. Explain what the paper does, what it found, and why it matters for bias/fairness/multilingual eval. Avoid translationese.",
          "paper_limitations": ["2-5 concise limitations, author-stated or strongly supported by the provided text only"],
          "why_relevant": ["exactly 2-4 concise bullets, each one actionable for FrenchBBQ / multilingual unified BBQ / LLM eval research"],
          "translation_notes": ["0-3 short notes only when terminology or cross-lingual interpretation genuinely matters; otherwise return []"]
        }}

        Additional guidance for `why_relevant`:
        - Prefer reuse-oriented bullets: benchmark construction, prompt design, multilingual transfer, annotation, ambiguity handling, metric choice, failure analysis, robustness.
        - Avoid generic bullets like 'this paper is relevant to fairness research'.

        Paper text:
        <<<PAPER_TEXT_BEGIN>>>
        {paper_text}
        <<<PAPER_TEXT_END>>>
        """
    ).strip()


def prepare_qwen_front_excerpt(full_text: str, max_chars: int = DEFAULT_QWEN_MAX_INPUT_CHARS) -> str:
    text = (full_text or "").strip()
    if len(text) <= max_chars:
        return text
    head = text[:max_chars].rstrip()
    return (
        "[FIRST ~8 PAGES / FRONT SECTION ONLY]\n"
        f"{head}\n\n"
        "[REMAINING PAPER OMITTED FOR BATCH PRECOMPUTE]"
    )


def build_extraction_prompt(*, project_id: str, record: dict[str, Any], schema_summary: str) -> str:
    return dedent(
        f"""
        {_SHARED_SYSTEM_PROMPT}

        Task: Produce structured extraction for review project `{project_id}`.

        Output must be valid JSON only.

        Schema:
        {schema_summary}

        Metadata:
        - paper_id: {record.get('paper_id', '')}
        - title: {record.get('title', '')}
        - year: {record.get('year', '')}
        - venue: {record.get('venue', '')}

        Available text fields:
        - abstract: {record.get('abstract', '')}
        - summary: {record.get('summary', '')}
        - zh_brief: {record.get('zh_brief', '')}
        - screening_rationale: {record.get('screening_rationale', '')}
        - paper_limitations: {record.get('paper_limitations', [])}

        Extraction rules:
        - Use the schema values conservatively and literally.
        - If a field is not stated, return null or [] rather than guessing.
        - Distinguish benchmark role carefully: introduces_benchmark vs uses_existing_benchmark vs compares_benchmarks vs critique_of_benchmark.
        - For `protected_attributes`, only include actual social attributes or groups studied in the paper; do not put vague populations unless they are the object of fairness analysis.
        - For `language_scope`, prefer monolingual unless the paper truly compares or constructs across multiple languages.
        - For `bias_type`, choose the most central type rather than a broad umbrella.
        - Keep `review_gap_tags` short, concrete, and useful for future benchmark design.
        - Return JSON only, with no prose before or after.
        """
    ).strip()


def _extract_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if not raw:
        raise ValueError("empty qwen output")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    file_match = re.search(r"written to [`']([^`'\n]+\.json)[`']", raw, flags=re.I)
    if file_match:
        path = Path(file_match.group(1)).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise ValueError(f"no JSON object found in qwen output: {raw[:300]}")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Qwen output was not a JSON object")
    return data


def _extract_output_json_path(text: str) -> Path | None:
    raw = text.strip()
    if not raw:
        return None
    candidates = re.findall(r"(?:`)?((?:output|\./output|/[^`\s]+output)/[^`\s]+\.json)(?:`)?", raw)
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if path.exists():
            return path
    return None


def _explicit_done_output_path(text: str) -> Path | None:
    raw = text.strip()
    if not raw:
        return None
    match = re.search(r"DONE:\s*(/[^\s`]+\.json)", raw)
    if not match:
        return None
    path = Path(match.group(1))
    return path if path.exists() else None


def _build_file_mode_prompt(prompt: str, output_path: Path) -> str:
    return (
        prompt
        + "\n\nOUTPUT INSTRUCTIONS:\n"
        + f"1. Write the final JSON object exactly to this file path: {output_path}\n"
        + "2. The file content must be valid JSON only, with no markdown fences.\n"
        + f"3. After writing the file, reply in stdout with exactly: DONE: {output_path}\n"
        + "4. Do not print the JSON to stdout. Do not print any other text.\n"
    )


def run_qwen_json(prompt: str, *, model: str | None = None, timeout: int = 600, qwen_command: str | None = None) -> dict[str, Any]:
    cmd = [qwen_command or DEFAULT_QWEN_COMMAND, "-y"]
    if model:
        cmd += ["-m", model]
    _ensure_dirs()
    fixed_output_path = QWEN_TMP_OUTPUT_DIR / f"qwen-{int(time.time() * 1000)}-{hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:10]}.json"
    attempts = [
        _build_file_mode_prompt(prompt, fixed_output_path),
        _build_file_mode_prompt(
            prompt + "\n\nIMPORTANT: Follow the output instructions exactly. Use the file path provided.",
            fixed_output_path,
        ),
        prompt,
        prompt + "\n\nIMPORTANT: Return valid JSON only. No markdown fences. No 'Done.'. No extra commentary.",
    ]
    last_error: Exception | None = None
    for candidate_prompt in attempts:
        proc = subprocess.run(cmd, input=candidate_prompt, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            last_error = RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "qwen failed")
            continue
        explicit_path = _explicit_done_output_path(proc.stdout) or _explicit_done_output_path(proc.stderr)
        if explicit_path is not None:
            try:
                data = json.loads(explicit_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception as e:
                last_error = e
                continue
        try:
            return _extract_json(proc.stdout)
        except ValueError:
            output_path = _extract_output_json_path(proc.stdout) or _extract_output_json_path(proc.stderr)
            if output_path is not None:
                try:
                    data = json.loads(output_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        return data
                except Exception as e:
                    last_error = e
                    continue
            last_error = ValueError(proc.stdout.strip()[:300] or proc.stderr.strip()[:300] or "invalid qwen output")
            continue
    raise last_error or RuntimeError("qwen failed")


def generate_summary_bundle(*, paper_id: str, title: str, year: str | int | None, venue: str, paper_text: str, model: str | None = None) -> dict[str, Any]:
    prompt = build_summary_prompt(
        paper_id=paper_id,
        title=title,
        year=year,
        venue=venue,
        paper_text=prepare_qwen_front_excerpt(paper_text),
    )
    data = run_qwen_json(prompt, model=model)
    return {
        "summary": str(data.get("summary") or "").strip(),
        "zh_brief": str(data.get("zh_brief") or "").strip(),
        "paper_limitations": [str(x).strip() for x in (data.get("paper_limitations") or []) if str(x).strip()],
        "why_relevant": [str(x).strip() for x in (data.get("why_relevant") or []) if str(x).strip()],
        "translation_notes": [str(x).strip() for x in (data.get("translation_notes") or []) if str(x).strip()],
    }


def generate_review_extraction(*, project_id: str, record: dict[str, Any], schema_summary: str, model: str | None = None) -> dict[str, Any]:
    prompt = build_extraction_prompt(project_id=project_id, record=record, schema_summary=schema_summary)
    return run_qwen_json(prompt, model=model)


def get_cached_summary_bundle(record: dict[str, Any] | None = None, *, source_url: str = "", paper_id: str = "") -> dict[str, Any] | None:
    if record:
        source_url = str(record.get("source_url") or source_url or "")
        paper_id = str(record.get("paper_id") or paper_id or "")
    payload = load_precompute(source_url=source_url, paper_id=paper_id)
    if not payload:
        return None
    bundle = payload.get("summary_bundle") or {}
    if not isinstance(bundle, dict):
        return None
    return bundle


def get_cached_review_extraction(project_id: str, record: dict[str, Any] | None = None, *, source_url: str = "", paper_id: str = "") -> dict[str, Any] | None:
    if record:
        source_url = str(record.get("source_url") or source_url or "")
        paper_id = str(record.get("paper_id") or paper_id or "")
    payload = load_precompute(source_url=source_url, paper_id=paper_id)
    if not payload:
        return None
    all_extractions = payload.get("review_extractions") or {}
    if not isinstance(all_extractions, dict):
        return None
    extraction = all_extractions.get(project_id)
    return extraction if isinstance(extraction, dict) else None


def merge_candidate_with_precompute(candidate: dict[str, Any]) -> dict[str, Any]:
    bundle = get_cached_summary_bundle(candidate)
    if not bundle:
        return candidate
    merged = dict(candidate)
    summary = str(bundle.get("summary") or "").strip()
    zh_brief = str(bundle.get("zh_brief") or "").strip()
    limitations = bundle.get("paper_limitations") or []
    if summary:
        merged["summary"] = summary
    if zh_brief:
        merged["zh_brief"] = zh_brief
    if isinstance(limitations, list) and limitations:
        merged["paper_limitations"] = [str(x).strip() for x in limitations if str(x).strip()]
    return merged
