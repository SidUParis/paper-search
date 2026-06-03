from __future__ import annotations

import json
from pathlib import Path

from paper_search.reader_context import build_paper_context, load_reader_index, make_head_tail_excerpt, related_papers


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    fulltext = tmp_path / "vault" / "fulltext" / "paper.md"
    fulltext.parent.mkdir(parents=True)
    fulltext.write_text("INTRO " + "a" * 120 + "\nRESULTS important ending", encoding="utf-8")
    papers = [
        {
            "paper_id": "p1",
            "title": "Multilingual Bias Benchmark",
            "abstract": "Abstract about BBQ fairness",
            "summary": "Summary about multilingual BBQ",
            "zh_brief": "中文简述",
            "limitations": "Small language set",
            "topic_slug": "bias-fairness",
            "source_label": "ACL",
            "local_fulltext": str(fulltext),
            "figures": [
                {
                    "kind": "image",
                    "title": "Figure 1 · Dataset pipeline",
                    "page": 3,
                    "src": "assets/paper-assets/p1/fig1.png",
                    "caption": "Pipeline for multilingual BBQ data construction.",
                },
                {
                    "kind": "table",
                    "title": "Table 2 · Accuracy by language",
                    "page": 6,
                    "src": "assets/paper-assets/p1/table2.csv",
                    "preview": [["Language", "Accuracy"], ["French", "71"]],
                },
            ],
            "tags": ["BBQ", "fairness"],
        },
        {
            "paper_id": "p2",
            "title": "Dialogue Summarization",
            "summary": "Meeting summary paper",
            "topic_slug": "conv-summarization",
            "source_label": "arxiv",
        },
    ]
    (site / "data" / "papers.json").write_text(json.dumps(papers), encoding="utf-8")
    return site


def test_load_reader_index_keys_by_paper_id_and_slug_like_title(tmp_path: Path):
    index = load_reader_index(_site(tmp_path))

    assert "p1" in index
    assert index["p1"]["title"] == "Multilingual Bias Benchmark"
    assert index["multilingual-bias-benchmark"]["paper_id"] == "p1"


def test_make_head_tail_excerpt_preserves_beginning_and_ending():
    text = "BEGIN " + "x" * 100 + " ENDING"

    excerpt = make_head_tail_excerpt(text, max_chars=40)

    assert "BEGIN" in excerpt
    assert "ENDING" in excerpt
    assert "[MIDDLE OMITTED" in excerpt
    assert len(excerpt) <= 120


def test_build_paper_context_uses_metadata_and_allowed_fulltext(tmp_path: Path):
    site = _site(tmp_path)

    context = build_paper_context(site, "p1", mode="balanced", allowed_roots=[tmp_path])

    assert context.paper["title"] == "Multilingual Bias Benchmark"
    assert "[Title] Multilingual Bias Benchmark" in context.text
    assert "[Chinese brief] 中文简述" in context.text
    assert "[Fulltext excerpt]" in context.text
    assert "RESULTS important ending" in context.text


def test_build_paper_context_includes_extracted_visual_assets(tmp_path: Path):
    site = _site(tmp_path)

    context = build_paper_context(site, "p1", mode="balanced", allowed_roots=[tmp_path])

    assert "[Extracted visuals]" in context.text
    assert "Figure 1 · Dataset pipeline" in context.text
    assert "Pipeline for multilingual BBQ data construction" in context.text
    assert "Table 2 · Accuracy by language" in context.text
    assert "French | 71" in context.text
    assert "Extracted visuals" in context.sources


def test_build_paper_context_rejects_fulltext_outside_allowed_roots(tmp_path: Path):
    site = _site(tmp_path)
    data_path = site / "data" / "papers.json"
    papers = json.loads(data_path.read_text(encoding="utf-8"))
    papers[0]["local_fulltext"] = "/etc/passwd"
    data_path.write_text(json.dumps(papers), encoding="utf-8")

    context = build_paper_context(site, "p1", mode="balanced", allowed_roots=[tmp_path])

    assert "[Fulltext excerpt]" not in context.text
    assert "root:" not in context.text


def test_related_papers_returns_lexical_matches(tmp_path: Path):
    site = _site(tmp_path)

    matches = related_papers(site, "BBQ fairness", top_k=1)

    assert len(matches) == 1
    assert matches[0]["paper_id"] == "p1"
