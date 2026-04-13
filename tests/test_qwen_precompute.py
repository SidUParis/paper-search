from __future__ import annotations

import json
import sys
from types import SimpleNamespace


def test_merge_candidate_with_precompute_prefers_cached_fields(monkeypatch):
    from paper_search.qwen_precompute import merge_candidate_with_precompute
    import paper_search.qwen_precompute as qwen_precompute

    monkeypatch.setattr(
        qwen_precompute,
        "get_cached_summary_bundle",
        lambda record=None, **kwargs: {
            "summary": "cached summary",
            "zh_brief": "缓存中文简述",
            "paper_limitations": ["limitation a"],
        },
    )

    candidate = {
        "paper_id": "demo-paper",
        "source_url": "https://example.com/paper",
        "summary": "old summary",
        "zh_brief": "",
        "paper_limitations": [],
    }
    merged = merge_candidate_with_precompute(candidate)

    assert merged["summary"] == "cached summary"
    assert merged["zh_brief"] == "缓存中文简述"
    assert merged["paper_limitations"] == ["limitation a"]


def test_get_cached_review_extraction_returns_none_without_identifiers():
    from paper_search.qwen_precompute import get_cached_review_extraction

    assert get_cached_review_extraction("multilingual-bias-benchmark-landscape", {}) is None


def test_extract_record_uses_cached_precompute_before_openrouter(monkeypatch):
    from paper_search.review_projects import load_review_project
    import paper_search.review_extraction as review_extraction

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "BasqBBQ: QA Benchmark for Social Biases in LLMs for Basque",
        "abstract": "First BBQ benchmark for Basque and English.",
        "summary": "Introduces BasqBBQ and includes human evaluation notes.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
        "source_url": "https://example.com/basqbbq",
        "paper_id": "2025-zulaika-basqbbq",
    }

    monkeypatch.setattr(
        review_extraction,
        "get_cached_review_extraction",
        lambda project_id, record=None, **kwargs: {
            "benchmark_name": "basqbbq",
            "human_evaluation_used": True,
            "paper_type": "survey",
            "language_scope": "monolingual",
        },
    )
    monkeypatch.setattr(
        review_extraction,
        "_llm_fallback_extract",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fallback should not run when cached extraction exists")),
    )

    extraction = review_extraction.extract_record(project, record)
    assert extraction["benchmark_name"] == "basqbbq"
    assert extraction["human_evaluation_used"] is True
    assert extraction["paper_type"] == "benchmark"
    assert extraction["language_scope"] == "multilingual"


def test_summarize_topic_fulltext_uses_cached_bundle_before_openrouter(monkeypatch):
    monkeypatch.setitem(sys.modules, "bs4", SimpleNamespace(BeautifulSoup=object))
    monkeypatch.setitem(sys.modules, "arxiv", SimpleNamespace())
    import paper_search.fulltext_pipeline as fulltext_pipeline

    class FakeNotion:
        def __init__(self):
            self.data_sources = SimpleNamespace(query=self.query)
            self.pages = SimpleNamespace(update=self.update)
            self.updated = []

        def query(self, **kwargs):
            return {
                "results": [
                    {
                        "id": "page-1",
                        "url": "https://notion.so/page-1",
                        "properties": {
                            "Title": {"title": [{"plain_text": "Demo Paper"}]},
                            "Authors": {"rich_text": [{"plain_text": "Alice, Bob"}]},
                            "Published": {"date": {"start": "2025-01-01"}},
                            "URL": {"url": "https://example.com/demo"},
                            "Summary": {"rich_text": []},
                        },
                    }
                ],
                "has_more": False,
            }

        def update(self, **kwargs):
            self.updated.append(kwargs)

    fake_notion = FakeNotion()
    monkeypatch.setattr(fulltext_pipeline, "load_topics", lambda: {"bias-fairness": {"acl_data_source_id": "ds1", "acl_database_id": "db1"}})
    monkeypatch.setattr(fulltext_pipeline, "get_notion_client", lambda: fake_notion)
    monkeypatch.setattr(
        fulltext_pipeline,
        "get_full_text",
        lambda url, force_refresh=False: {
            "text": "x" * 3500,
            "cache_path": "/tmp/demo.md",
            "document_cache_path": "/tmp/demo.pdf",
            "resolved_url": url,
        },
    )
    monkeypatch.setattr(
        fulltext_pipeline,
        "get_cached_summary_bundle",
        lambda **kwargs: {
            "summary": "cached structured summary",
            "zh_brief": "缓存中文简述",
            "paper_limitations": ["cached limitation"],
        },
    )
    monkeypatch.setattr(
        fulltext_pipeline,
        "summarize_full_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenRouter summary should not run when cached bundle exists")),
    )
    monkeypatch.setattr(
        fulltext_pipeline,
        "summarize_full_text_zh_brief_and_limitations",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenRouter zh_brief should not run when cached bundle exists")),
    )
    monkeypatch.setattr(
        "paper_search.obsidian_export.export_paper_note",
        lambda **kwargs: {"note_path": "/tmp/demo-note.md"},
    )

    events = list(fulltext_pipeline.summarize_topic_fulltext("bias-fairness", source="acl", limit=1))
    done = [e for e in events if e.get("status") == "done"]
    total = [e for e in events if e.get("total")]

    assert len(done) == 1
    assert total[-1]["success"] == 1
    assert fake_notion.updated
    summary_payload = fake_notion.updated[0]["properties"]["Summary"]["rich_text"][0]["text"]["content"]
    assert summary_payload == "cached structured summary"


def test_run_qwen_json_supports_output_file_mode(tmp_path, monkeypatch):
    import paper_search.qwen_precompute as qwen_precompute

    out_dir = tmp_path / "tmp"
    out_dir.mkdir(parents=True)
    out_file = out_dir / "demo.json"
    payload = {"summary": "ok", "zh_brief": "好"}
    out_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(qwen_precompute, "QWEN_TMP_OUTPUT_DIR", out_dir)

    class Result:
        returncode = 0
        stdout = f"DONE: {out_file}"
        stderr = ""

    monkeypatch.setattr(qwen_precompute.subprocess, "run", lambda *args, **kwargs: Result())

    data = qwen_precompute.run_qwen_json("prompt")
    assert data == payload


def test_run_qwen_json_prefers_inline_json(monkeypatch):
    import paper_search.qwen_precompute as qwen_precompute

    class Result:
        returncode = 0
        stdout = '{"summary": "inline", "zh_brief": "直接返回"}'
        stderr = ""

    monkeypatch.setattr(qwen_precompute.subprocess, "run", lambda *args, **kwargs: Result())

    data = qwen_precompute.run_qwen_json("prompt")
    assert data["summary"] == "inline"


def test_run_qwen_json_sends_prompt_via_stdin_not_argv(monkeypatch):
    import paper_search.qwen_precompute as qwen_precompute

    captured = {}

    class Result:
        returncode = 0
        stdout = '{"summary": "stdin", "zh_brief": "标准输入"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(qwen_precompute.subprocess, "run", fake_run)

    prompt = "very long prompt body"
    data = qwen_precompute.run_qwen_json(prompt, model="demo-model", timeout=123)

    assert data["summary"] == "stdin"
    assert captured["cmd"] == [qwen_precompute.DEFAULT_QWEN_COMMAND, "-y", "-m", "demo-model"]
    assert prompt in captured["kwargs"]["input"]
    assert "OUTPUT INSTRUCTIONS" in captured["kwargs"]["input"]
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["timeout"] == 123


def test_qwen_precompute_batch_continues_after_generation_error(monkeypatch, capsys):
    import scripts.qwen_precompute_batch as batch

    records = [
        {
            "notion_page_id": "page-1",
            "notion_url": "https://notion.so/page-1",
            "paper_id": "paper-1",
            "topic_slug": "bias-fairness",
            "title": "Paper 1",
            "authors": "A",
            "year": 2025,
            "venue": "ACL",
            "source_label": "ACL",
            "source_url": "https://example.com/1",
            "abstract": "",
            "summary": "",
            "zh_brief": "",
            "paper_limitations": [],
        },
        {
            "notion_page_id": "page-2",
            "notion_url": "https://notion.so/page-2",
            "paper_id": "paper-2",
            "topic_slug": "bias-fairness",
            "title": "Paper 2",
            "authors": "B",
            "year": 2025,
            "venue": "ACL",
            "source_label": "ACL",
            "source_url": "https://example.com/2",
            "abstract": "",
            "summary": "",
            "zh_brief": "",
            "paper_limitations": [],
        },
    ]
    state = {"done_keys": []}
    saved_payloads = []

    monkeypatch.setattr(batch, "iter_topic_pages", lambda topic, source='all': iter(records))
    monkeypatch.setattr(batch, "load_state", lambda: state)
    monkeypatch.setattr(batch, "save_state", lambda s: state.update(s))
    monkeypatch.setattr(batch, "load_precompute", lambda **kwargs: None)
    monkeypatch.setattr(batch, "cache_key", lambda **kwargs: kwargs["paper_id"])
    monkeypatch.setattr(batch, "get_full_text", lambda url: {"text": "x" * 4000, "cache_path": "/tmp/demo.md"})

    def fake_generate_summary_bundle(**kwargs):
        if kwargs["paper_id"] == "paper-1":
            raise ValueError("bad qwen json")
        return {
            "summary": "ok",
            "zh_brief": "好",
            "paper_limitations": [],
            "why_relevant": [],
            "translation_notes": [],
        }

    monkeypatch.setattr(batch, "generate_summary_bundle", fake_generate_summary_bundle)
    monkeypatch.setattr(batch, "save_precompute", lambda payload, **kwargs: saved_payloads.append(payload) or __import__("pathlib").Path("/tmp/cache.json"))
    monkeypatch.setattr(batch, "export_paper_note", lambda **kwargs: None)
    monkeypatch.setattr(batch, "MIN_FULLTEXT_CHARS", 10)
    monkeypatch.setattr(sys, "argv", ["qwen_precompute_batch.py", "--topic", "bias-fairness", "--limit", "2"])

    batch.main()
    out = json.loads(capsys.readouterr().out)

    assert out["errors"] == 1
    assert out["updated"] == 1
    assert any(item["status"] == "error" and item["paper_id"] == "paper-1" for item in out["results"])
    assert any(item["status"] == "done" and item["paper_id"] == "paper-2" for item in out["results"])
    assert state["done_keys"] == ["paper-2"]
    assert state["last_error"]["paper_id"] == "paper-1"
