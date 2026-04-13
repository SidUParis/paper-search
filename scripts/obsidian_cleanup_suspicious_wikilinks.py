#!/usr/bin/env python3
"""Clean up suspicious Obsidian wikilinks that can create garbage unresolved nodes.

What it fixes:
- Links like [[(]] [[)]] [[[ESSAY]] [[[ Prompt: {} ;Response: {} ]] ...
These often come from PDF->markdown fulltext extraction artifacts.

Safety rules:
- Only touches markdown files under <vault>/papers/fulltext by default.
- Only edits link targets that contain brackets/parentheses or start with '[[['.
- Replaces them with inline code literals (so the text remains visible but is not a wikilink).

Output:
- Prints counts of replacements.

"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]|\n]+?)(?:\|([^\]\n]+))?\]\]")


def is_suspicious_target(t: str) -> bool:
    if not t:
        return False
    if t.startswith("[["):
        return True
    if any(ch in t for ch in "[](){}"):
        return True
    # Extremely short punctuation targets
    if t.strip() in {"(", ")", "[", "]", "{", "}"}:
        return True
    return False


def replacement_for(link_text: str, target: str, alias: str | None) -> str:
    # Preserve what user would see.
    display = alias if alias else target
    display = display.strip()
    # Inline code to keep it visible.
    return f"`{display}`"


def clean_text(text: str) -> tuple[str, int]:
    n = 0

    def _sub(m: re.Match):
        nonlocal n
        target = m.group(1)
        alias = m.group(2)
        if is_suspicious_target(target):
            n += 1
            return replacement_for(m.group(0), target, alias)
        return m.group(0)

    out = WIKILINK_RE.sub(_sub, text)
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--path", default="papers/fulltext", help="relative path under vault to scan")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    root = vault / args.path
    files = sorted(root.rglob("*.md"))

    total_rep = 0
    changed_files = 0

    for p in files:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        new, n = clean_text(txt)
        if n:
            total_rep += n
            changed_files += 1
            if not args.dry_run:
                p.write_text(new, encoding="utf-8")

    print(f"scanned_files={len(files)}")
    print(f"changed_files={changed_files}")
    print(f"replacements={total_rep}")


if __name__ == "__main__":
    main()
