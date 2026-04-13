#!/usr/bin/env python3
"""Backfill Obsidian paper notes with Chinese brief + limitations from cached full text.

Scope:
- Only touches Obsidian notes under vault/papers/*.md where venue == "ACL".
- Only updates the content inside sections:
  - "# 中文简述"
  - "# Limitations / caveats"
- Uses local_fulltext path from YAML frontmatter.
- Does NOT touch Notion.

State:
- Writes progress to cache/backfill_obsidian_zh_lim_state.json for resumability.

Run:
  source .venv/bin/activate
  python scripts/backfill_obsidian_zh_lim.py --limit 50

"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# repo root
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "/home/orange/Documents/Obsidian Vault"))
PAPERS_DIR = VAULT / "papers"
STATE_PATH = ROOT / "cache" / "backfill_obsidian_zh_lim_state.json"


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_frontmatter(note_text: str) -> dict[str, str]:
    if not note_text.startswith("---"):
        return {}
    parts = note_text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = parts[1]
    out: dict[str, str] = {}
    for line in fm.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _section_needs_placeholder(note_text: str, header: str) -> bool:
    if header not in note_text:
        return False
    after = note_text.split(header, 1)[1]
    # look only at near region to avoid false positives elsewhere
    snippet = after[:400]
    return "待补充。" in snippet


def _replace_section(note_text: str, header: str, new_body: str) -> str:
    """Replace content between `header` and the next top-level '# ' header (or EOF)."""
    # Ensure header exists
    idx = note_text.find(header)
    if idx == -1:
        return note_text

    start = idx + len(header)

    # Find the next top-level header after start
    m = re.search(r"\n# ", note_text[start:])
    if m:
        end = start + m.start()
    else:
        end = len(note_text)

    # Normalize new body
    body = new_body.strip() + "\n"
    # Ensure exactly one blank line between header and body
    replacement = "\n\n" + body + "\n"

    return note_text[:start] + replacement + note_text[end:]


def _format_limitations_md(limitations: list[str]) -> str:
    lims = [x.strip() for x in limitations if x and x.strip()]
    if not lims:
        return "待补充。"
    return "\n".join(f"- {x}" for x in lims)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50, help="Max notes to update in this run")
    ap.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between notes")
    args = ap.parse_args()

    from paper_search.summarizer import summarize_full_text_zh_brief_and_limitations

    state = _load_state()
    done = set(state.get("done_notes", []))
    updated = 0
    errors = 0
    skipped = 0

    notes = sorted([p for p in PAPERS_DIR.glob("*.md") if p.name != "index.md"])

    for note_path in notes:
        if updated >= args.limit:
            break

        # idempotency
        if str(note_path) in done:
            continue

        try:
            text = note_path.read_text(encoding="utf-8", errors="ignore")
            fm = _parse_frontmatter(text)
            venue = (fm.get("venue") or "").strip().strip('"').strip("'")
            if venue.upper() != "ACL":
                continue

            needs_zh = _section_needs_placeholder(text, "# 中文简述")
            needs_lim = _section_needs_placeholder(text, "# Limitations / caveats")
            if not (needs_zh or needs_lim):
                skipped += 1
                done.add(str(note_path))
                continue

            fulltext_path = (fm.get("local_fulltext") or "").strip().strip('"').strip("'")
            if not fulltext_path or not Path(fulltext_path).exists():
                errors += 1
                state.setdefault("missing_fulltext", []).append(str(note_path))
                done.add(str(note_path))
                _save_state({**state, "done_notes": sorted(done), "updated": updated, "errors": errors, "skipped": skipped})
                continue

            fulltext = Path(fulltext_path).read_text(encoding="utf-8", errors="ignore")
            extras: dict[str, Any] = summarize_full_text_zh_brief_and_limitations(
                fm.get("title") or note_path.stem,
                fulltext,
            )
            zh = (extras.get("zh_brief") or "").strip() or "待补充。"
            lim_md = _format_limitations_md(extras.get("limitations") or [])

            if needs_zh:
                text = _replace_section(text, "# 中文简述", zh)
            if needs_lim:
                text = _replace_section(text, "# Limitations / caveats", lim_md)

            note_path.write_text(text, encoding="utf-8")
            updated += 1
            done.add(str(note_path))

            if updated % 5 == 0:
                _save_state({**state, "done_notes": sorted(done), "updated": updated, "errors": errors, "skipped": skipped})

            print(f"UPDATED {updated}: {note_path.name}")
            time.sleep(max(0.0, args.sleep))

        except Exception as e:
            errors += 1
            state.setdefault("errors", []).append({"note": str(note_path), "error": str(e)[:500]})
            done.add(str(note_path))
            _save_state({**state, "done_notes": sorted(done), "updated": updated, "errors": errors, "skipped": skipped})
            print(f"ERROR {note_path.name}: {str(e)[:200]}")

    _save_state({**state, "done_notes": sorted(done), "updated": updated, "errors": errors, "skipped": skipped})
    print(json.dumps({"updated": updated, "errors": errors, "skipped": skipped, "state": str(STATE_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
