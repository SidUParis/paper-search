from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from paper_search.reader_ranking import build_ranking_messages, local_rank_papers, rank_papers_with_llm


class FakeRegistry:
    pass


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "papers.json").write_text(
        json.dumps(
            [
                {
                    "paper_id": "p1",
                    "title": "FrenchBBQ: A French Bias Benchmark",
                    "summary": "French BBQ benchmark for social bias evaluation.",
                    "topic_slug": "bias-fairness",
                    "source_label": "arxiv",
                    "tags": ["BBQ", "French"],
                },
                {
                    "paper_id": "p2",
                    "title": "General summarization model",
                    "summary": "Dialogue summarization.",
                    "topic_slug": "conv-summarization",
                    "source_label": "ACL",
                    "tags": ["summarization"],
                },
            ]
        ),
        encoding="utf-8",
    )
    return site


def test_build_ranking_messages_include_json_contract_and_candidates(tmp_path: Path):
    messages = build_ranking_messages(
        _site(tmp_path),
        query="FrenchBBQ multilingual bias",
        candidate_limit=2,
    )

    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "Return strict JSON" in user
    assert "FrenchBBQ" in user
    assert "p1" in user
    assert "p2" in user


def test_rank_papers_with_llm_returns_ordered_scored_papers(tmp_path: Path, monkeypatch):
    site = _site(tmp_path)

    def fake_kwargs(*_args, **_kwargs):
        return {"base_url": "https://example.test", "api_key": "secret", "model": "demo", "messages": []}

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kw: SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content=json.dumps(
                                        {
                                            "results": [
                                                {"paper_id": "p1", "score": 0.96, "reason": "FrenchBBQ bias benchmark"},
                                                {"paper_id": "p2", "score": 0.12, "reason": "Mostly summarization"},
                                            ]
                                        }
                                    )
                                )
                            )
                        ]
                    )
                )
            )

    monkeypatch.setattr("paper_search.reader_ranking.build_chat_request_kwargs", fake_kwargs)
    result = rank_papers_with_llm(
        registry=FakeRegistry(),
        site_dir=site,
        payload={"query": "FrenchBBQ multilingual bias", "limit": 2, "use_llm": True},
        client_factory=FakeClient,
    )

    assert result["query"] == "FrenchBBQ multilingual bias"
    assert result["results"][0]["paper_id"] == "p1"
    assert result["results"][0]["score"] == 0.96
    assert result["results"][0]["paper"]["title"] == "FrenchBBQ: A French Bias Benchmark"
    assert "api_key" not in json.dumps(result).lower()


def test_local_rank_papers_finds_exact_title_without_llm(tmp_path: Path):
    site = _site(tmp_path)

    results = local_rank_papers(site, "FrenchBBQ: A French Bias Benchmark", limit=3)

    assert results[0]["paper_id"] == "p1"
    assert results[0]["score"] == 1.0
    assert "本地标题" in results[0]["reason"]


def test_rank_papers_with_llm_short_circuits_full_title_lookup(tmp_path: Path, monkeypatch):
    site = _site(tmp_path)

    def fake_kwargs(*_args, **_kwargs):  # pragma: no cover - should not be called for exact title lookup
        raise AssertionError("LLM should not be called for exact title/database-existence lookup")

    monkeypatch.setattr("paper_search.reader_ranking.build_chat_request_kwargs", fake_kwargs)
    result = rank_papers_with_llm(
        registry=FakeRegistry(),
        site_dir=site,
        payload={"query": "FrenchBBQ: A French Bias Benchmark", "limit": 2},
        client_factory=lambda **_kwargs: None,
    )

    assert result["source"] == "local-index"
    assert result["model"] == "local-index"
    assert result["results"][0]["paper_id"] == "p1"


def test_rank_papers_with_llm_falls_back_to_local_results_on_bad_json(tmp_path: Path, monkeypatch):
    site = _site(tmp_path)

    def fake_kwargs(*_args, **_kwargs):
        return {"base_url": "https://example.test", "api_key": "secret", "model": "demo", "messages": []}

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kw: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content='{"results": [{"paper_id": "p1" "score": 1}]}'))]
                    )
                )
            )

    monkeypatch.setattr("paper_search.reader_ranking.build_chat_request_kwargs", fake_kwargs)
    result = rank_papers_with_llm(
        registry=FakeRegistry(),
        site_dir=site,
        payload={"query": "FrenchBBQ multilingual bias", "limit": 2, "use_llm": True},
        client_factory=FakeClient,
    )

    assert result["source"] == "local-index"
    assert "LLM rerank failed" in result["warning"]
    assert result["results"][0]["paper_id"] == "p1"
