"""Background jobs for the private reader admin dashboard."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any
from uuid import uuid4

from dotenv import dotenv_values
from paper_search.topics import list_topics

ALLOWED_UPDATE_SOURCES = {"all", "acl", "arxiv", "scholar"}
ALLOWED_ACTIONS = {"update", "update-all", "fulltext", "regenerate", "fulltext-and-regenerate", "extract-figures", "notebooklm-audio"}


@dataclass(slots=True)
class ReaderJob:
    job_id: str
    action: str
    status: str
    created_at: str
    updated_at: str
    commands: list[list[str]]
    return_codes: list[int]
    output_tail: str = ""
    error: str = ""


_LOCK = threading.Lock()
_RUNNING: dict[str, threading.Thread] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jobs_dir(state_dir: Path) -> Path:
    path = state_dir / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(state_dir: Path, job_id: str) -> Path:
    return _jobs_dir(state_dir) / f"{job_id}.json"


def _write_job(state_dir: Path, job: ReaderJob) -> None:
    _job_path(state_dir, job.job_id).write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")


def _read_job(path: Path) -> ReaderJob | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReaderJob(**data)
    except Exception:
        return None


def list_jobs(state_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    paths = sorted(_jobs_dir(state_dir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    jobs = [_read_job(path) for path in paths]
    return [asdict(job) for job in jobs if job is not None]


def get_job(state_dir: Path, job_id: str) -> dict[str, Any] | None:
    path = _job_path(state_dir, job_id)
    if not path.exists():
        return None
    job = _read_job(path)
    return asdict(job) if job else None


def _safe_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _optional_limit(value: Any, min_value: int = 1, max_value: int = 10000) -> int | None:
    """Parse an optional export limit; blank/all/none means export the whole library."""

    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"", "all", "none", "null", "0"}:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return max(min_value, min(parsed, max_value))


def _subprocess_env(cwd: Path) -> dict[str, str]:
    """Build a subprocess env with private project .env values, without logging them."""
    import os

    env = os.environ.copy()
    candidates = [cwd / ".env", Path.home() / "paper-search" / ".env"]
    for env_path in candidates:
        if env_path.exists():
            for key, value in dotenv_values(env_path).items():
                if value is not None and key not in env:
                    env[key] = value
    return env


def _topic_commands(payload: dict[str, Any]) -> list[list[str]]:
    source = str(payload.get("source") or "all").lower()
    if source not in ALLOWED_UPDATE_SOURCES:
        raise ValueError(f"invalid source: {source}")
    topic = str(payload.get("topic") or "bias-fairness").strip()
    if not topic:
        raise ValueError("topic is required")
    max_results = _safe_int(payload.get("max_results"), 50, 1, 500)
    summarize = bool(payload.get("summarize", False))
    cmd = [sys.executable, "-m", "paper_search.cli", "update", topic, "--source", source, "--max-results", str(max_results)]
    if not summarize:
        cmd.append("--no-summarize")
    return [cmd]


def build_commands(payload: dict[str, Any], *, site_dir: Path, profile: str, site_title: str) -> list[list[str]]:
    action = str(payload.get("action") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"invalid action: {action}")
    source = str(payload.get("source") or "all").lower()
    if source not in ALLOWED_UPDATE_SOURCES:
        raise ValueError(f"invalid source: {source}")
    fulltext_limit = _safe_int(payload.get("limit"), 50, 1, 1000)
    export_limit = _optional_limit(payload.get("limit"))
    commands: list[list[str]] = []
    if action == "notebooklm-audio":
        paper_key = str(payload.get("paper_key") or payload.get("paper_id") or "").strip()
        if not paper_key:
            raise ValueError("paper_key is required")
        commands.append([
            sys.executable,
            "scripts/generate_notebooklm_audio_for_reader.py",
            "--site-dir",
            str(site_dir),
            "--paper-key",
            paper_key,
        ])
        return commands
    if action == "update":
        commands.extend(_topic_commands(payload))
    elif action == "update-all":
        topics = [slug for slug, _cfg in list_topics()]
        if not topics:
            raise ValueError("no topics configured")
        for topic_slug in topics:
            commands.extend(_topic_commands({**payload, "topic": topic_slug, "source": source}))
    elif action in {"fulltext", "fulltext-and-regenerate"}:
        commands.append([sys.executable, "-m", "paper_search.cli", "summarize-fulltext-all", "--source", source, "--limit", str(fulltext_limit)])
    if action in {"regenerate", "fulltext-and-regenerate", "extract-figures"}:
        export_cmd = [
            sys.executable,
            "-m",
            "paper_search.cli",
            "export-reader-site",
            "--profile",
            profile,
            "--output",
            str(site_dir),
        ]
        if export_limit is not None:
            export_cmd.extend(["--limit", str(export_limit)])
        export_cmd.extend([
            "--site-title",
            site_title,
        ])
        commands.append(export_cmd)
    return commands


def start_job(payload: dict[str, Any], *, state_dir: Path, site_dir: Path, profile: str, site_title: str, cwd: Path) -> dict[str, Any]:
    commands = build_commands(payload, site_dir=site_dir, profile=profile, site_title=site_title)
    if not commands:
        raise ValueError("job has no commands")
    job = ReaderJob(
        job_id=uuid4().hex[:12],
        action=str(payload.get("action") or ""),
        status="queued",
        created_at=_now(),
        updated_at=_now(),
        commands=commands,
        return_codes=[],
    )
    _write_job(state_dir, job)

    thread = threading.Thread(target=_run_job, args=(job.job_id, state_dir, cwd), daemon=True)
    with _LOCK:
        _RUNNING[job.job_id] = thread
    thread.start()
    return asdict(job)


def _run_job(job_id: str, state_dir: Path, cwd: Path) -> None:
    path = _job_path(state_dir, job_id)
    job = _read_job(path)
    if job is None:
        return
    output = ""
    try:
        job.status = "running"
        job.updated_at = _now()
        _write_job(state_dir, job)
        for command in job.commands:
            proc = subprocess.run(
                command,
                cwd=str(cwd),
                env=_subprocess_env(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60 * 60,
            )
            output += f"\n$ {' '.join(command)}\n{proc.stdout}\n"
            job.return_codes.append(proc.returncode)
            job.output_tail = output[-12000:]
            job.updated_at = _now()
            _write_job(state_dir, job)
            if proc.returncode != 0:
                job.status = "failed"
                job.error = f"command failed with exit code {proc.returncode}"
                break
        else:
            job.status = "completed"
    except subprocess.TimeoutExpired as exc:
        job.status = "failed"
        job.error = f"timeout: {exc}"
        output += f"\nTIMEOUT: {exc}\n"
    except Exception as exc:  # pragma: no cover - defensive guard for background thread
        job.status = "failed"
        job.error = str(exc)
        output += f"\nERROR: {exc}\n"
    finally:
        job.output_tail = output[-12000:]
        job.updated_at = _now()
        _write_job(state_dir, job)
        with _LOCK:
            _RUNNING.pop(job_id, None)
