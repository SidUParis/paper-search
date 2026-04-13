#!/usr/bin/env python3
"""DEBUGGED topic classifier: use ABSTRACT + sentence embeddings, but train from pseudo-seed keyword rules.

Why:
- Your existing manual `research_directions` labels have huge overlap between bias & fairness
  (in this vault: bias+fairness together dominates), so a supervised classifier cannot
  learn to separate them. It will output nearly identical bias/fairness scores.

Fix:
- Build a small but *separable* training set using high-precision keyword rules on abstracts:
  - bias := SOCIAL bias / stereotypes / toxicity / hate / bias benchmarks
  - fairness := algorithmic fairness metrics / constraints (demographic parity, equalized odds...)
  - summarization := summarization / ROUGE / factual consistency in summaries / meeting/dialog summarization
- Exclude ambiguous overlaps from training.
- Train 3 one-vs-rest logistic regressions on embeddings.
- Write back:
  - auto_topic.primary (argmax)
  - auto_topic.scores
  - auto_topic.highconf (labels linked in Connections)
- Connections: ONLY link topics in highconf (no longer force-link primary).

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

# High precision seed patterns
BIAS_PAT = re.compile(
    r"(stereotyp|stereo ?set|crows-?pairs|winobias|bbq|social bias|demographic bias|racial bias|gender bias|religious bias|toxicit|hate speech|sexism|racism|prejudice|xenophob|islamophob|antisemit|homophob)",
    re.I,
)
FAIRNESS_PAT = re.compile(
    r"(algorithmic fairness|fair classification|demographic parity|equalized odds|equal opportunity|disparate impact|counterfactual fairness|individual fairness|group fairness|fairness constraint|fairness-aware|fairness metric|fairlearn)",
    re.I,
)
SUMM_PAT = re.compile(
    r"(summari[sz]ation|meeting summarization|dialogue summarization|multi-document summarization|query-focused summarization|rouge|bart for summarization|faithful summar|factual consistency|hallucination in summar)",
    re.I,
)


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
    for lab in LABELS:
        concept = LABEL_TO_CONCEPT[lab]
        body = re.sub(rf"^\s*-\s+\[\[{re.escape(concept)}\]\]\s*$\n?", "", body, flags=re.M)
    return body


def ensure_connections_links(body: str, concepts: List[str]) -> str:
    concepts = [c for c in concepts if c]
    concepts = list(dict.fromkeys(concepts))
    if not concepts:
        return body

    m = re.search(r"(^#\s+Connections\s*$)", body, flags=re.M)
    ins = "".join([f"- [[{c}]]\n" for c in concepts])

    if m:
        start = m.end()
        nxt = re.search(r"^#\s+", body[start:], flags=re.M)
        end = start + nxt.start() if nxt else len(body)
        section = body[start:end]
        new_section = "\n" + ins + section.lstrip("\n")
        return body[:start] + new_section + body[end:]

    if not body.endswith("\n"):
        body += "\n"
    body += "\n# Connections\n" + ins
    return body


def seed_labels(text: str) -> Dict[str, int]:
    # returns dict of {label: 0/1} for seeds, can be multi; caller will handle overlap
    return {
        "bias": 1 if BIAS_PAT.search(text) else 0,
        "fairness": 1 if FAIRNESS_PAT.search(text) else 0,
        "summarization": 1 if SUMM_PAT.search(text) else 0,
    }


def compute_highconf(primary: str, probs: Dict[str, float], primary_abs: float, extra_abs: float, rel: float) -> List[str]:
    out = []
    p1 = probs[primary]
    if p1 >= primary_abs:
        out.append(primary)
    for lab in LABELS:
        if lab == primary:
            continue
        if probs[lab] >= extra_abs and probs[lab] >= rel * p1:
            out.append(lab)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--model", default="allenai/specter2_base")
    ap.add_argument("--primary-abs", type=float, default=0.75)
    ap.add_argument("--extra-abs", type=float, default=0.80)
    ap.add_argument("--rel", type=float, default=0.95)
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

    # Load + extract
    for p in files:
        txt = p.read_text(encoding="utf-8", errors="ignore")
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
            # fallback to summary chunk
            idx = body.find("# Summary")
            abstract = (body[idx : idx + 2000] if idx != -1 else body[:2000]).strip()

        text = build_embedding_text(str(title), abstract)
        seed = seed_labels(text)
        rows.append({
            "path": p,
            "fm": fm,
            "body": body,
            "text": text,
            "seed": seed,
            "abstract_found": abstract_found,
        })

    # Build pseudo training set (exclude overlaps)
    train_idx = []
    y = []
    for i, r in enumerate(rows):
        labs = [lab for lab in LABELS if r["seed"][lab] == 1]
        if len(labs) != 1:
            continue
        lab = labs[0]
        # One-vs-rest labels for 3 classifiers
        y_row = [1 if lab == L else 0 for L in LABELS]
        train_idx.append(i)
        y.append(y_row)

    y_train = np.array(y, dtype=np.int32)
    if y_train.shape[0] < 50:
        print(f"WARNING: only {y_train.shape[0]} pseudo-labeled training rows. Consider expanding regex seeds.")

    # Embed
    model, device = load_model(args.model)
    print(f"MODEL: {args.model} on {device}")
    X_all = model.encode([r["text"] for r in rows], batch_size=32, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)

    # Train
    from sklearn.linear_model import LogisticRegression

    X_train = X_all[np.array(train_idx, dtype=int)] if train_idx else X_all[:0]

    clfs = []
    for j in range(len(LABELS)):
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        if X_train.shape[0] >= 10 and y_train[:, j].sum() >= 2:
            clf.fit(X_train, y_train[:, j])
            clfs.append(clf)
        else:
            clfs.append(None)

    # Predict probs
    probs_mat = np.zeros((len(rows), len(LABELS)), dtype=np.float32)
    for j in range(len(LABELS)):
        if clfs[j] is None:
            # fallback: uniform low
            probs_mat[:, j] = 1.0 / len(LABELS)
        else:
            probs_mat[:, j] = clfs[j].predict_proba(X_all)[:, 1]

    updated = dt.datetime.now().strftime("%Y-%m-%d")

    counts_primary = {lab: 0 for lab in LABELS}
    counts_high = {lab: 0 for lab in LABELS}
    multi = 0
    linked_any = 0

    for i, r in enumerate(rows):
        pr = {lab: float(probs_mat[i, j]) for j, lab in enumerate(LABELS)}
        primary = max(LABELS, key=lambda lab: pr[lab])
        counts_primary[primary] += 1

        highconf = compute_highconf(primary, pr, primary_abs=args.primary_abs, extra_abs=args.extra_abs, rel=args.rel)
        if highconf:
            linked_any += 1
        if len(highconf) >= 2:
            multi += 1
        for lab in highconf:
            counts_high[lab] += 1

        auto_topic = {
            "model": args.model,
            "device": device,
            "source": "abstract",
            "updated": updated,
            "train_mode": "pseudo_seed_regex",
            "seed_regex": {
                "bias": BIAS_PAT.pattern,
                "fairness": FAIRNESS_PAT.pattern,
                "summarization": SUMM_PAT.pattern,
            },
            "train_size": int(len(train_idx)),
            "primary": primary,
            "scores": pr,
            "highconf": highconf,
            "primary_abs": float(args.primary_abs),
            "extra_abs": float(args.extra_abs),
            "rel": float(args.rel),
            "abstract_found": bool(r["abstract_found"]),
        }

        fm = dict(r["fm"])
        fm["auto_topic"] = auto_topic
        fm_dump = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=120).strip()

        body = remove_topic_concept_links(r["body"])
        concepts = [LABEL_TO_CONCEPT[lab] for lab in highconf]
        body = ensure_connections_links(body, concepts)

        new_text = "---\n" + fm_dump + "\n---\n" + body
        if not args.dry_run:
            r["path"].write_text(new_text, encoding="utf-8")

    rep = []
    rep.append("# Auto-topic assignment (abstract-based) — DEBUGGED\n")
    rep.append(f"Model: `{args.model}`\n")
    rep.append(f"Device: `{device}`\n")
    rep.append(f"Papers processed: `{len(rows)}`\n")
    rep.append(f"Pseudo-labeled train size: `{len(train_idx)}` (single-label regex hits only)\n")
    rep.append(f"Abstract missing fallback count: `{abs_missing}`\n")
    rep.append("\n## Linking rule (Connections)\n")
    rep.append(f"- link primary only if prob >= `{args.primary_abs}`\n")
    rep.append(f"- link extra label if prob >= `{args.extra_abs}` AND prob >= `{args.rel}` * primary_prob\n")
    rep.append(f"- papers linked to at least one topic: `{linked_any}`\n")
    rep.append(f"- multi-topic papers (>=2 links): `{multi}`\n")

    rep.append("\n## Primary label counts (argmax, for coarse aggregation)\n")
    for lab in LABELS:
        rep.append(f"- {lab}: `{counts_primary[lab]}`\n")

    rep.append("\n## High-confidence linked counts (graph edges)\n")
    for lab in LABELS:
        rep.append(f"- {lab}: `{counts_high[lab]}`\n")

    out_path = vault / "dashboards" / "auto-topic-assignment-report.md"
    out_path.write_text("".join(rep), encoding="utf-8")

    print(f"REPORT: {out_path}")


if __name__ == "__main__":
    main()
