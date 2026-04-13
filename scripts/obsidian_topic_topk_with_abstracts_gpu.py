#!/usr/bin/env python3
"""Generate Top-K topic candidates for Obsidian paper notes using GPU sentence-transformers,
including FULL ABSTRACT text for each candidate.

- Trains a classifier from existing `research_directions`.
- Ranks candidates per label excluding already-labeled.
- Uses Title+Abstract embeddings (abstract extracted from `local_fulltext`).
- Writes a markdown report with <details> blocks containing the full abstract.

Output:
  <vault>/dashboards/auto-topic-topk-candidates-with-abstracts.md

"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import yaml

LABELS = ["bias", "fairness", "summarization"]
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

    # end at next heading
    m2 = re.search(r"^#{1,3}\s+", txt[start:], flags=re.M)
    end = start + m2.start() if m2 else len(txt)

    abstract = txt[start:end].strip()

    # cleanup markdown artifacts and excessive whitespace
    abstract = re.sub(r"\n{3,}", "\n\n", abstract)
    abstract = re.sub(r"[ \t]+", " ", abstract)
    abstract = abstract.strip()

    if not abstract:
        return None
    return abstract[:max_chars]


def build_embedding_text(title: str, abstract: str) -> str:
    # Keep it simple and stable across notes
    title = (title or "").strip()
    abstract = (abstract or "").strip()
    return f"Title: {title}\n\nAbstract: {abstract}".strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--model", default="allenai/specter2_base")
    ap.add_argument("--topk", type=int, default=200)
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

        rd = normalize_rd(fm.get("research_directions"))
        y = [1 if lab in rd else 0 for lab in LABELS]

        title = fm.get("title") or p.stem
        lf = fm.get("local_fulltext")
        abstract = None
        if isinstance(lf, str) and lf:
            fpath = Path(lf)
            if fpath.exists():
                abstract = extract_abstract_from_fulltext(fpath)

        if not abstract:
            abs_missing += 1
            # fallback to note body (still include something for audit)
            # take Summary section chunk if exists else first 2000 chars
            idx = body.find("# Summary")
            abstract = (body[idx: idx + 2000] if idx != -1 else body[:2000]).strip()

        emb_text = build_embedding_text(title, abstract)

        rows.append({
            "path": p,
            "title": title,
            "rd": rd,
            "y": y,
            "emb_text": emb_text,
            "abstract": abstract,
        })

    X_train_text = [r["emb_text"] for r in rows if any(r["y"])]
    y_train = np.array([r["y"] for r in rows if any(r["y"])], dtype=np.int32)

    model, device = load_model(args.model)
    print(f"MODEL: {args.model} on {device}")

    X_train = model.encode(X_train_text, batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)

    from sklearn.linear_model import LogisticRegression

    clfs = []
    for j in range(len(LABELS)):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        clf.fit(X_train, y_train[:, j])
        clfs.append(clf)

    X_all = model.encode([r["emb_text"] for r in rows], batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)
    probs = np.stack([clfs[j].predict_proba(X_all)[:, 1] for j in range(len(LABELS))], axis=1)

    out = []
    out.append("# Auto topic Top-K candidates (with full abstracts)\n")
    out.append(f"Model: `{args.model}`\n")
    out.append(f"Device: `{device}`\n")
    out.append(f"Papers scanned: `{len(rows)}`\n")
    out.append(f"Training labeled: `{len(X_train_text)}`\n")
    out.append(f"Abstract missing (fallback used): `{abs_missing}`\n")
    out.append(f"TopK per label: `{args.topk}`\n")

    for j, lab in enumerate(LABELS):
        out.append(f"\n---\n\n## {lab} — Top {args.topk} (excluding already-labeled)\n")
        idxs = [i for i, r in enumerate(rows) if lab not in r["rd"]]
        ranked = sorted(idxs, key=lambda i: float(probs[i, j]), reverse=True)[: args.topk]
        for rank, i in enumerate(ranked, start=1):
            r = rows[i]
            p = float(probs[i, j])
            out.append(f"{rank:>3}. `{r['path'].name}` (p={p:.3f})\n")
            out.append(f"     - title: {r['title']}\n")
            out.append(f"     - current research_directions: {r['rd']}\n")
            out.append("     <details><summary>Abstract</summary>\n\n")
            # keep abstract as-is (may contain newlines)
            out.append(r["abstract"].strip() + "\n\n")
            out.append("     </details>\n")

    out_path = vault / "dashboards" / "auto-topic-topk-candidates-with-abstracts.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(out), encoding="utf-8")
    print(f"OUT: {out_path}")


if __name__ == "__main__":
    main()
