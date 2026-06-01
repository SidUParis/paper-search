from __future__ import annotations

import sys
from pathlib import Path

from paper_search.reader_jobs import build_commands


def test_regenerate_job_builds_safe_command(tmp_path: Path):
    commands = build_commands(
        {"action": "regenerate", "limit": 25},
        site_dir=tmp_path / "site",
        profile="private",
        site_title="Reader",
    )

    assert commands == [
        [
            sys.executable,
            "-m",
            "paper_search.cli",
            "export-reader-site",
            "--profile",
            "private",
            "--output",
            str(tmp_path / "site"),
            "--limit",
            "25",
            "--site-title",
            "Reader",
        ]
    ]


def test_update_job_rejects_unknown_action(tmp_path: Path):
    try:
        build_commands({"action": "rm -rf /"}, site_dir=tmp_path, profile="private", site_title="Reader")
    except ValueError as exc:
        assert "invalid action" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_fulltext_job_builds_summarize_command(tmp_path: Path):
    commands = build_commands(
        {"action": "fulltext-and-regenerate", "source": "acl", "limit": 3},
        site_dir=tmp_path / "site",
        profile="private",
        site_title="Reader",
    )

    assert commands[0][:4] == [sys.executable, "-m", "paper_search.cli", "summarize-fulltext-all"]
    assert "acl" in commands[0]
    assert commands[1][3] == "export-reader-site"


def test_extract_figures_job_regenerates_site_without_running_update(tmp_path: Path):
    commands = build_commands(
        {"action": "extract-figures", "limit": 7},
        site_dir=tmp_path / "site",
        profile="private",
        site_title="Reader",
    )

    assert len(commands) == 1
    assert commands[0][3] == "export-reader-site"
    assert "--limit" in commands[0]
    assert "7" in commands[0]
