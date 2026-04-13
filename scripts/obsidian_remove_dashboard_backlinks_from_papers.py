#!/usr/bin/env python3
"""Remove dashboard links from paper notes to avoid dashboards becoming giant hub nodes.

This cleans wikilinks like:
- [[dashboards/bias-dashboard]]
- [[dashboards/fairness-dashboard]]
- [[dashboards/summarization-dashboard]]
- [[dashboards/read-next]]
- [[dashboards/knowledge-graph-hub]]

Scope:
- Only touches <vault>/papers/*.md

"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

DASH_LINK_RE = re.compile(
    r"^\s*-\s+\[\[dashboards/(bias-dashboard|fairness-dashboard|summarization-dashboard|read-next|knowledge-graph-hub)\]\]\s*$\n?",
    re.M,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    root = vault / "papers"
    files = sorted(root.glob("*.md"))

    changed = 0
    removed_total = 0

    for p in files:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        new, n = DASH_LINK_RE.subn("", txt)
        if n:
            changed += 1
            removed_total += n
            if not args.dry_run:
                p.write_text(new, encoding="utf-8")

    print(f"papers_scanned={len(files)}")
    print(f"papers_changed={changed}")
    print(f"dashboard_links_removed={removed_total}")


if __name__ == "__main__":
    main()
