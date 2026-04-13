from __future__ import annotations

import json
from pathlib import Path

from paper_search.review_projects import load_review_project
from paper_search.review_store import load_jsonl, get_review_dir

PROJECTS = [
    'review_projects/examples/multilingual-bias-benchmark-landscape.yaml',
    'review_projects/examples/conversational-summarization-landscape.yaml',
    'review_projects/examples/sycophancy-evaluation-landscape.yaml',
]

MAX_PER_PROJECT = 4


def build_sample() -> list[dict]:
    sample = []
    for cfg in PROJECTS:
        project = load_review_project(cfg)
        review_dir = get_review_dir(project.review_project_id)
        rows = load_jsonl(review_dir / 'extractions.jsonl')
        kept = 0
        for row in rows:
            extraction = row.get('extraction') or {}
            sample.append(
                {
                    'project_id': project.review_project_id,
                    'title': row.get('title', ''),
                    'abstract': row.get('abstract', ''),
                    'summary': row.get('summary', ''),
                    'heuristic_extraction': extraction,
                }
            )
            kept += 1
            if kept >= MAX_PER_PROJECT:
                break
    return sample


def main() -> None:
    out = Path('/home/orange/paper-search/cache/local_benchmark_sample.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    sample = build_sample()
    out.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out))
    print(len(sample))


if __name__ == '__main__':
    main()
