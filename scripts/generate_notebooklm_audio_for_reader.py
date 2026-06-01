#!/usr/bin/env python3
"""Generate a NotebookLM deep-dive audio file for one reader-site paper.

This script is intentionally narrow and auditable: it reads the generated
private reader `data/papers.json`, uploads the selected paper's local PDF (or a
safe PDF/source URL) to NotebookLM via the local `notebooklm` CLI, generates a
Simplified-Chinese long deep-dive audio artifact, downloads it to a local cache,
and writes the local MP3 path back into `papers.json` as `notebooklm_audio`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


def _run(cmd: list[str], *, timeout: int = 600) -> str:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}")
    return proc.stdout.strip()


def _json_or_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _find_uuid(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("id", "notebook_id", "notebookId", "artifact_id", "artifactId"):
            value = data.get(key)
            if isinstance(value, str) and re.match(r"^[0-9a-f-]{8,}$", value):
                return value
        for value in data.values():
            try:
                found = _find_uuid(value)
                if found:
                    return found
            except ValueError:
                pass
    elif isinstance(data, list):
        for value in data:
            try:
                found = _find_uuid(value)
                if found:
                    return found
            except ValueError:
                pass
    elif isinstance(data, str):
        match = re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,}", data, flags=re.I)
        if match:
            return match.group(0)
    raise ValueError(f"could not find UUID in NotebookLM output: {str(data)[:300]}")


def _safe_filename(text: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")
    return (name or fallback)[:120]


def _pdf_like_url(url: str) -> str:
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/") + ("" if url.endswith(".pdf") else ".pdf")
    match = re.match(r"^(https?://aclanthology\.org/[^/]+)/?$", url)
    if match:
        return match.group(1) + ".pdf"
    return url


def _source_for_paper(paper: dict[str, Any]) -> tuple[str, str, list[str]]:
    local = str(paper.get("local_document") or "").strip()
    if local:
        path = Path(local).expanduser()
        if path.exists() and path.is_file():
            return str(path), "file", ["--type", "file", "--mime-type", "application/pdf"]
    url = _pdf_like_url(str(paper.get("source_url") or "").strip())
    if url.startswith("http://") or url.startswith("https://"):
        return url, "url", ["--type", "url"]
    raise ValueError("paper has no local PDF or source URL suitable for NotebookLM")


def _load_papers(site_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    data_path = site_dir / "data" / "papers.json"
    papers = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(papers, list):
        raise ValueError(f"invalid papers data: {data_path}")
    return data_path, papers


def generate_audio(
    *,
    site_dir: Path,
    paper_key: str,
    output_root: Path,
    language: str,
    length: str,
    notebooklm_cmd: str,
    timeout: int,
    force: bool,
) -> dict[str, Any]:
    data_path, papers = _load_papers(site_dir)
    paper = next((p for p in papers if str(p.get("paper_id") or "") == paper_key), None)
    if paper is None:
        raise KeyError(f"paper not found: {paper_key}")

    existing = str(paper.get("notebooklm_audio") or "").strip()
    if existing and not force:
        if existing.startswith(("http://", "https://")) or Path(existing).expanduser().exists():
            return {"ok": True, "status": "existing", "paper_id": paper_key, "audio_path": existing}

    source, source_kind, source_flags = _source_for_paper(paper)
    title = str(paper.get("title") or paper_key).strip()
    notebook_title = f"AI Reader Audio — {title[:120]}"

    created = _json_or_text(_run([notebooklm_cmd, "create", notebook_title, "--json"], timeout=120))
    notebook_id = _find_uuid(created)

    _run(
        [notebooklm_cmd, "source", "add", source, "-n", notebook_id, *source_flags, "--title", title[:160], "--json"],
        timeout=timeout,
    )

    prompt = (
        "请基于这篇论文生成一个中文深度访谈式 audio overview："
        "先解释研究问题和背景，再拆解方法、实验、主要发现、局限性，"
        "最后明确说明它与 Sidney 的 LLM bias/fairness / FrenchBBQ / MultilingualBBQ 博士研究的关系。"
    )
    generated = _json_or_text(
        _run(
            [
                notebooklm_cmd,
                "generate",
                "audio",
                prompt,
                "-n",
                notebook_id,
                "--format",
                "deep-dive",
                "--length",
                length,
                "--language",
                language,
                "--no-wait",
                "--json",
            ],
            timeout=timeout,
        )
    )
    artifact_id = _find_uuid(generated)
    _run([notebooklm_cmd, "artifact", "wait", artifact_id, "-n", notebook_id, "--timeout", str(timeout), "--json"], timeout=timeout + 60)

    output_root.mkdir(parents=True, exist_ok=True)
    out_path = output_root / f"{_safe_filename(paper_key, 'paper')}_notebooklm-deepdive.mp3"
    _run([notebooklm_cmd, "download", "audio", str(out_path), "-n", notebook_id, "--artifact", artifact_id, "--force", "--json"], timeout=timeout)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"NotebookLM audio download did not create a non-empty file: {out_path}")

    paper["notebooklm_audio"] = str(out_path)
    data_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "status": "generated",
        "paper_id": paper_key,
        "notebook_id": notebook_id,
        "artifact_id": artifact_id,
        "source_kind": source_kind,
        "audio_path": str(out_path),
        "player_url": f"/paper-assets/audio/{paper_key}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", default="private-reader-site")
    parser.add_argument("--paper-key", required=True)
    parser.add_argument("--output-root", default="cache/notebooklm_audio")
    parser.add_argument("--language", default="zh_Hans")
    parser.add_argument("--length", choices=["short", "default", "long"], default="long")
    parser.add_argument("--notebooklm-cmd", default="notebooklm")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = generate_audio(
            site_dir=Path(args.site_dir),
            paper_key=args.paper_key,
            output_root=Path(args.output_root),
            language=args.language,
            length=args.length,
            notebooklm_cmd=args.notebooklm_cmd,
            timeout=args.timeout,
            force=args.force,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
