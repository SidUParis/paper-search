#!/usr/bin/env python3
"""Auto-classify Obsidian paper notes into topics (bias/fairness/summarization) using GPU sentence-transformers.

Design goals:
- Conservative: only add labels when confidence is high.
- Minimal edits: only touch research_directions + add concept links under # Connections.
- Train from existing vault labels if available.

Usage:
  source /home/orange/.hermes/hermes-agent/venv/bin/activate
  python /home/orange/paper-search/scripts/obsidian_topic_classify_gpu.py \
    --vault "/home/orange/Documents/Obsidian Vault" \
    --model "allenai/specter2_base" \
    --threshold 0.90 \
    --max-files 0

"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

LABELS = ["bias", "fairness", "summarization"]
LABEL_TO_CONCEPT = {
    "bias": "concepts/bias-research",
    "fairness": "concepts/fairness-research",
    "summarization": "concepts/summarization-research",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def load_model(model_name: str):
    # Lazy import to fail fast if deps missing
    from sentence_transformers import SentenceTransformer

    # Prefer CUDA if available
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(model_name, device=device)
    return model, device


def extract_frontmatter(text: str) -> Tuple[Dict[str, Any], str, str]:
    """Return (frontmatter_dict, frontmatter_block_including_delims, body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, "", text
    fm_text = m.group(1)
    fm = yaml.safe_load(fm_text) or {}
    block = text[: m.end()]
    body = text[m.end() :]
    return fm, block, body


def normalize_rd(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, str):
                out.append(x)
        return out
    return []


def build_paper_text(fm: Dict[str, Any], body: str) -> str:
    # Use a compact but informative slice for embeddings.
    title = fm.get("title") or ""
    # Pull One-sentence takeaway + Summary section if present.
    # Keep length bounded.
    chunks = [f"Title: {title}".strip()]

    # Prefer explicit sections if present
    for header in ["# One-sentence takeaway", "# Summary", "# 中文简述"]:
        idx = body.find(header)
        if idx != -1:
            seg = body[idx : idx + 2500]
            chunks.append(seg)

    if len(chunks) == 1:
        # fallback to first 3000 chars
        chunks.append(body[:3000])

    text = "\n\n".join(chunks)
    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def update_research_directions_in_frontmatter_block(block: str, add_labels: List[str]) -> str:
    """Update research_directions inside the existing frontmatter block. If missing, insert near review_status."""
    if not block:
        return block

    lines = block.splitlines(keepends=False)
    # Find frontmatter content region
    # lines[0] is --- ; find second ---
    try:
        end_idx = lines.index("---", 1)
    except ValueError:
        return block

    fm_lines = lines[1:end_idx]

    # Locate research_directions key
    key_idx = None
    for i, ln in enumerate(fm_lines):
        if re.match(r"^research_directions\s*:\s*(.*)$", ln):
            key_idx = i
            break

    def render_block(labels: List[str]) -> List[str]:
        out = ["research_directions:"]
        for lab in labels:
            out.append(f"- {lab}")
        return out

    if key_idx is not None:
        # Consume existing list items
        j = key_idx + 1
        while j < len(fm_lines) and re.match(r"^\s*-\s+", fm_lines[j]):
            j += 1
        # Parse existing
        existing = []
        for ln in fm_lines[key_idx + 1 : j]:
            m = re.match(r"^\s*-\s+(.*)$", ln)
            if m:
                existing.append(m.group(1).strip())
        merged = sorted(set([*existing, *add_labels]), key=lambda x: (LABELS.index(x) if x in LABELS else 999, x))
        new_lines = fm_lines[:key_idx] + render_block(merged) + fm_lines[j:]
        fm_lines = new_lines
    else:
        # Insert after review_status if possible, else before end
        insert_at = None
        for i, ln in enumerate(fm_lines):
            if re.match(r"^review_status\s*:\s*", ln):
                insert_at = i + 1
                break
        if insert_at is None:
            insert_at = len(fm_lines)
        new_block = render_block(sorted(set(add_labels), key=lambda x: LABELS.index(x)))
        fm_lines = fm_lines[:insert_at] + new_block + fm_lines[insert_at:]

    new_lines_all = ["---", *fm_lines, "---", ""]
    return "\n".join(new_lines_all)


def ensure_connections_links(body: str, add_concepts: List[str]) -> str:
    """Ensure - [[concepts/...]] links exist under # Connections. Minimal edits."""
    if not add_concepts:
        return body

    # Already present?
    missing = []
    for c in add_concepts:
        wikilink = f"[[{c}]]"
        if wikilink not in body:
            missing.append(c)
    if not missing:
        return body

    # Find # Connections section
    m = re.search(r"(^#\s+Connections\s*$)", body, flags=re.M)
    if m:
        start = m.end()
        # Insert after header line
        # Find next header or end
        next_h = re.search(r"^#\s+", body[start:], flags=re.M)
        if next_h:
            section_end = start + next_h.start()
        else:
            section_end = len(body)
        section = body[start:section_end]
        ins = "".join([f"- [[{c}]]\n" for c in missing])
        # Put at top of section
        new_section = "\n" + ins + section.lstrip("\n")
        return body[:start] + new_section + body[section_end:]

    # No Connections section: append
    ins = "\n# Connections\n" + "".join([f"- [[{c}]]\n" for c in missing])
    if not body.endswith("\n"):
        body += "\n"
    return body + ins


@dataclass
class PaperNote:
    path: Path
    fm: Dict[str, Any]
    fm_block: str
    body: str
    text_for_embed: str


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--model", default="allenai/specter2_base")
    ap.add_argument("--threshold", type=float, default=0.90)
    ap.add_argument("--max-files", type=int, default=0, help="0 means all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    papers_dir = vault / "papers"
    if not papers_dir.exists():
        print(f"ERROR: papers dir not found: {papers_dir}", file=sys.stderr)
        sys.exit(2)

    md_files = sorted(papers_dir.glob("*.md"))
    if args.max_files and args.max_files > 0:
        md_files = md_files[: args.max_files]

    # Load notes
    notes: List[PaperNote] = []
    for p in md_files:
        text = p.read_text(encoding="utf-8")
        fm, fm_block, body = extract_frontmatter(text)
        if not fm:
            continue
        notes.append(
            PaperNote(
                path=p,
                fm=fm,
                fm_block=fm_block,
                body=body,
                text_for_embed=build_paper_text(fm, body),
            )
        )

    # Build training set from existing research_directions
    X_train_text = []
    y_train = []
    unlabeled = []
    for n in notes:
        rd = normalize_rd(n.fm.get("research_directions"))
        y = [1 if lab in rd else 0 for lab in LABELS]
        if any(y):
            X_train_text.append(n.text_for_embed)
            y_train.append(y)
        else:
            unlabeled.append(n)

    if len(X_train_text) < 20:
        print(f"WARNING: only {len(X_train_text)} labeled papers found; accuracy may be limited.")

    model, device = load_model(args.model)
    print(f"MODEL: {args.model} on {device}")

    # Embed training
    X_train = model.encode(X_train_text, batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)
    y_train = np.array(y_train, dtype=np.int32)

    # Train 3 one-vs-rest logistic regressions
    from sklearn.linear_model import LogisticRegression

    clfs = []
    for j, lab in enumerate(LABELS):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(X_train, y_train[:, j])
        clfs.append(clf)

    # Predict unlabeled
    changed = []
    if unlabeled:
        X_un = model.encode([n.text_for_embed for n in unlabeled], batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)
        probs = np.stack([clfs[j].predict_proba(X_un)[:, 1] for j in range(len(LABELS))], axis=1)

        for n, pr in zip(unlabeled, probs):
            add = [lab for lab, p in zip(LABELS, pr) if p >= args.threshold]
            if not add:
                continue
            # Write back
            add_concepts = [LABEL_TO_CONCEPT[a] for a in add]
            new_fm_block = update_research_directions_in_frontmatter_block(n.fm_block, add)
            new_body = ensure_connections_links(n.body, add_concepts)
            new_text = new_fm_block + new_body

            if not args.dry_run:
                n.path.write_text(new_text, encoding="utf-8")
            changed.append((n.path, add, pr.tolist()))

    # Report
    report_lines = []
    report_lines.append(f"# Auto topic classification report\n")
    report_lines.append(f"Model: `{args.model}`\n")
    report_lines.append(f"Device: `{device}`\n")
    report_lines.append(f"Threshold: `{args.threshold}`\n")
    report_lines.append(f"Papers scanned: `{len(notes)}`\n")
    report_lines.append(f"Training labeled: `{len(X_train_text)}`\n")
    report_lines.append(f"Unlabeled: `{len(unlabeled)}`\n")
    report_lines.append(f"Changed: `{len(changed)}`\n")

    report_lines.append("\n## Changed files\n")
    for path, add, pr in changed[:200]:
        report_lines.append(f"- `{path.name}` → add {add} (probs={['{:.3f}'.format(x) for x in pr]})\n")

    out_path = vault / "dashboards" / "auto-topic-classification-report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(report_lines), encoding="utf-8")

    print(f"REPORT: {out_path}")
    print(f"CHANGED: {len(changed)}")


if __name__ == "__main__":
    main()
