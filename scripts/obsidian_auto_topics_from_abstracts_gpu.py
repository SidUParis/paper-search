#!/usr/bin/env python3
"""Assign 3-topic labels (bias/fairness/summarization) to all Obsidian paper notes using ABSTRACT embeddings.

Goal (per user request):
- Use abstract-based sentence model similarity/classification to group ALL papers into 3 buckets.
- If a paper scores well on 2 topics, link it to both (graph edge).

Implementation:
- Extract Abstract from each paper's `local_fulltext` markdown cache.
- Compute embeddings with sentence-transformers (default: allenai/specter2_base) on GPU if available.
- Train 3 one-vs-rest LogisticRegression models from existing `research_directions` labels.
- For every paper:
  - primary = argmax(prob)
  - links = [primary] + extra labels where:
      prob >= abs_threshold AND prob >= rel_threshold * primary_prob
    (this captures "two topics both have good scores")
- Write to YAML frontmatter as `auto_topic`.
- Under `# Connections`, ensure concept links reflect ONLY the computed `links`.
  (It removes the three concept links first, then re-adds the right ones.)

Outputs:
- <vault>/dashboards/auto-topic-assignment-report.md

"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
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
    from sentence_transformers import SentenceTransformer
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(model_name, device=device)
    return model, device


def extract_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    body = text[m.end() :]
    return fm, body


def normalize_rd(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str)]
    return []


def extract_abstract_from_fulltext(fulltext_path: Path, max_chars: int = 20000) -> Optional[str]:
    try:
        txt = fulltext_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    patterns = [
        r"^##\s+\*\*Abstract\*\*\s*$",
        r"^##\s+Abstract\s*$",
        r"^#\s+Abstract\s*$",
    ]

    start = None
    for pat in patterns:
        m = re.search(pat, txt, flags=re.M)
        if m:
            start = m.end()
            break
    if start is None:
        return None

    m2 = re.search(r"^#{1,3}\s+", txt[start:], flags=re.M)
    end = start + m2.start() if m2 else len(txt)

    abstract = txt[start:end].strip()
    abstract = re.sub(r"\n{3,}", "\n\n", abstract)
    abstract = re.sub(r"[ \t]+", " ", abstract)
    abstract = abstract.strip()

    if not abstract:
        return None
    return abstract[:max_chars]


def build_embedding_text(title: str, abstract: str) -> str:
    title = (title or "").strip()
    abstract = (abstract or "").strip()
    return f"Title: {title}\n\nAbstract: {abstract}".strip()


def remove_topic_concept_links(body: str) -> str:
    # Remove the exact concept link lines we manage.
    for lab in LABELS:
        concept = LABEL_TO_CONCEPT[lab]
        body = re.sub(rf"^\s*-\s+\[\[{re.escape(concept)}\]\]\s*$\n?", "", body, flags=re.M)
    return body


def ensure_connections_links(body: str, concepts: List[str]) -> str:
    concepts = [c for c in concepts if c]
    if not concepts:
        return body

    # Ensure unique
    concepts = list(dict.fromkeys(concepts))

    # Ensure # Connections section exists
    m = re.search(r"(^#\s+Connections\s*$)", body, flags=re.M)
    ins = "".join([f"- [[{c}]]\n" for c in concepts])

    if m:
        start = m.end()
        nxt = re.search(r"^#\s+", body[start:], flags=re.M)
        end = start + nxt.start() if nxt else len(body)
        section = body[start:end]
        # Insert at top of section
        new_section = "\n" + ins + section.lstrip("\n")
        return body[:start] + new_section + body[end:]

    if not body.endswith("\n"):
        body += "\n"
    body += "\n# Connections\n" + ins
    return body


def compute_links(primary: str, probs: Dict[str, float], abs_threshold: float, rel_threshold: float) -> List[str]:
    primary_p = probs[primary]
    links = [primary]
    for lab in LABELS:
        if lab == primary:
            continue
        p = probs[lab]
        if p >= abs_threshold and p >= rel_threshold * primary_p:
            links.append(lab)
    return links


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--model", default="allenai/specter2_base")
    ap.add_argument("--abs-threshold", type=float, default=0.60)
    ap.add_argument("--rel-threshold", type=float, default=0.85)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    papers_dir = vault / "papers"
    if not papers_dir.exists():
        print(f"ERROR: papers dir not found: {papers_dir}", file=sys.stderr)
        sys.exit(2)

    files = sorted(papers_dir.glob("*.md"))
    rows = []
    abs_missing = 0

    for p in files:
        txt = p.read_text(encoding="utf-8")
        fm, body = extract_frontmatter(txt)
        if not fm:
            continue

        title = fm.get("title") or p.stem
        lf = fm.get("local_fulltext")
        abstract = None
        if isinstance(lf, str) and lf:
            fp = Path(lf)
            if fp.exists():
                abstract = extract_abstract_from_fulltext(fp)

        abstract_found = True
        if not abstract:
            abstract_found = False
            abs_missing += 1
            idx = body.find("# Summary")
            abstract = (body[idx : idx + 2000] if idx != -1 else body[:2000]).strip()

        emb_text = build_embedding_text(str(title), abstract)
        rd = normalize_rd(fm.get("research_directions"))
        y = [1 if lab in rd else 0 for lab in LABELS]

        rows.append({
            "path": p,
            "fm": fm,
            "body": body,
            "emb_text": emb_text,
            "y": y,
            "abstract_found": abstract_found,
        })

    if not rows:
        print("No paper notes found.")
        return

    y_all = np.array([r["y"] for r in rows], dtype=np.int32)
    labeled_mask = np.array([any(r["y"]) for r in rows], dtype=bool)

    model, device = load_model(args.model)
    print(f"MODEL: {args.model} on {device}")

    X_all = model.encode([r["emb_text"] for r in rows], batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)

    from sklearn.linear_model import LogisticRegression

    X_train = X_all[labeled_mask]
    y_train = y_all[labeled_mask]
    if X_train.shape[0] < 50:
        print(f"WARNING: only {X_train.shape[0]} labeled papers.")

    clfs = []
    for j in range(len(LABELS)):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(X_train, y_train[:, j])
        clfs.append(clf)

    probs_mat = np.stack([clfs[j].predict_proba(X_all)[:, 1] for j in range(len(LABELS))], axis=1)

    updated = dt.datetime.now().strftime("%Y-%m-%d")

    counts_primary = {lab: 0 for lab in LABELS}
    counts_links = {lab: 0 for lab in LABELS}
    multi_count = 0

    for i, r in enumerate(rows):
        pr = {lab: float(probs_mat[i, j]) for j, lab in enumerate(LABELS)}
        primary = max(LABELS, key=lambda lab: pr[lab])
        counts_primary[primary] += 1

        links = compute_links(primary, pr, abs_threshold=args.abs_threshold, rel_threshold=args.rel_threshold)
        if len(links) >= 2:
            multi_count += 1

        for lab in links:
            counts_links[lab] += 1

        auto_topic = {
            "model": args.model,
            "device": device,
            "source": "abstract",
            "updated": updated,
            "scheme": "primary_plus_extras",
            "abs_threshold": float(args.abs_threshold),
            "rel_threshold": float(args.rel_threshold),
            "primary": primary,
            "scores": pr,
            "highconf": links,  # for backwards compatibility with existing concept queries
            "abstract_found": bool(r["abstract_found"]),
        }

        fm = dict(r["fm"])
        fm["auto_topic"] = auto_topic
        fm_dump = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=120).strip()

        # Rewrite body connections deterministically
        body = remove_topic_concept_links(r["body"])
        concepts = [LABEL_TO_CONCEPT[lab] for lab in links]
        body = ensure_connections_links(body, concepts)

        new_text = "---\n" + fm_dump + "\n---\n" + body
        if not args.dry_run:
            r["path"].write_text(new_text, encoding="utf-8")

    rep = []
    rep.append("# Auto-topic assignment (abstract-based)\n")
    rep.append(f"Model: `{args.model}`\n")
    rep.append(f"Device: `{device}`\n")
    rep.append(f"Papers processed: `{len(rows)}`\n")
    rep.append(f"Labeled for training: `{int(labeled_mask.sum())}`\n")
    rep.append(f"Abstract missing fallback count: `{abs_missing}`\n")
    rep.append("\n## Link rule\n")
    rep.append(f"- primary: always linked\n")
    rep.append(f"- extra label: prob >= `{args.abs_threshold}` AND prob >= `{args.rel_threshold}` * primary_prob\n")
    rep.append(f"- multi-topic papers (>=2 links): `{multi_count}`\n")

    rep.append("\n## Primary label counts (every paper gets one)\n")
    for lab in LABELS:
        rep.append(f"- {lab}: `{counts_primary[lab]}`\n")

    rep.append("\n## Linked counts (connections created)\n")
    for lab in LABELS:
        rep.append(f"- {lab}: `{counts_links[lab]}`\n")

    out_path = vault / "dashboards" / "auto-topic-assignment-report.md"
    out_path.write_text("".join(rep), encoding="utf-8")

    print(f"REPORT: {out_path}")


if __name__ == "__main__":
    main()
