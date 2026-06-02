from __future__ import annotations

import json
from pathlib import Path

from paper_search.reader_chat import build_chat_messages, generate_chat_response
from paper_search.reader_models import ModelProvider, ReaderModelRegistry


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "papers.json").write_text(
        """
        [
          {"paper_id":"p1","title":"Bias Benchmark","summary":"A BBQ fairness paper","topic_slug":"bias-fairness","source_label":"ACL"},
          {"paper_id":"p2","title":"Other Paper","summary":"Summarization","topic_slug":"summarization","source_label":"arxiv"}
        ]
        """,
        encoding="utf-8",
    )
    return site


def test_build_chat_messages_for_single_paper_includes_context_and_chinese_instruction(tmp_path: Path):
    messages = build_chat_messages(
        _site(tmp_path),
        question="这篇论文贡献是什么？",
        paper_key="p1",
        mode="balanced",
        allowed_roots=[tmp_path],
    )

    assert messages[0]["role"] == "system"
    assert "中文" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "[Title] Bias Benchmark" in messages[1]["content"]
    assert "这篇论文贡献是什么" in messages[1]["content"]


def test_build_chat_messages_can_include_reader_note_and_selected_visual(tmp_path: Path):
    messages = build_chat_messages(
        _site(tmp_path),
        question="结合我标注的位置解释实验。",
        paper_key="p1",
        reading_note="这里像 Notion margin note: FrenchBBQ 可复用。",
        selected_visual={"title": "Figure 2 · Pipeline", "page": 4, "caption": "Dataset pipeline"},
    )

    content = messages[1]["content"]
    assert "[Reader note]" in content
    assert "FrenchBBQ 可复用" in content
    assert "[Selected visual]" in content
    assert "Figure 2 · Pipeline" in content


def test_build_chat_messages_for_paper_defaults_to_full_local_fulltext(tmp_path: Path):
    site = tmp_path / "site"
    fulltext = tmp_path / "fulltext" / "p1.md"
    fulltext.parent.mkdir(parents=True)
    long_middle = "MIDDLE_SECTION_SENTINEL " + ("important middle evidence " * 1800)
    fulltext.write_text("INTRO PDF TEXT\n" + long_middle + "\nCONCLUSION PDF TEXT", encoding="utf-8")
    (site / "data").mkdir(parents=True)
    (site / "data" / "papers.json").write_text(
        json.dumps([{"paper_id": "p1", "title": "Full PDF Paper", "local_fulltext": str(fulltext)}]),
        encoding="utf-8",
    )

    messages = build_chat_messages(
        site,
        question="请根据整篇 PDF 回答。",
        paper_key="p1",
        allowed_roots=[tmp_path],
    )

    content = messages[1]["content"]
    assert "[Full PDF text]" in content
    assert "INTRO PDF TEXT" in content
    assert "MIDDLE_SECTION_SENTINEL" in content
    assert "CONCLUSION PDF TEXT" in content
    assert "[MIDDLE OMITTED FOR BREVITY]" not in content


def test_build_chat_messages_falls_back_to_full_pdf_document_text(tmp_path: Path):
    import fitz

    site = tmp_path / "site"
    pdf = tmp_path / "pdfs" / "p1.pdf"
    pdf.parent.mkdir(parents=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "PDF_DOCUMENT_SENTINEL full pdf body evidence")
    doc.save(pdf)
    doc.close()
    (site / "data").mkdir(parents=True)
    (site / "data" / "papers.json").write_text(
        json.dumps([{"paper_id": "p1", "title": "PDF Only Paper", "local_document": str(pdf)}]),
        encoding="utf-8",
    )

    messages = build_chat_messages(
        site,
        question="请根据整篇 PDF 回答。",
        paper_key="p1",
        allowed_roots=[tmp_path],
    )

    content = messages[1]["content"]
    assert "[Full PDF text]" in content
    assert "PDF_DOCUMENT_SENTINEL" in content


def test_build_chat_messages_falls_back_to_remote_pdf_source_text(tmp_path: Path, monkeypatch):
    from paper_search import reader_context

    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "papers.json").write_text(
        json.dumps([
            {
                "paper_id": "p1",
                "title": "ACL Remote PDF Paper",
                "source_url": "https://aclanthology.org/2025.emnlp-main.1640/",
            }
        ]),
        encoding="utf-8",
    )
    seen = {}

    def fake_remote_pdf_text(url: str, cache_key: str, cache_dir: Path) -> str:
        seen["url"] = url
        seen["cache_key"] = cache_key
        seen["cache_dir"] = cache_dir
        return "REMOTE_PDF_SENTINEL full remote pdf evidence"

    monkeypatch.setattr(reader_context, "_safe_extract_remote_pdf_text", fake_remote_pdf_text)

    messages = build_chat_messages(site, question="请根据整篇 PDF 回答。", paper_key="p1")

    content = messages[1]["content"]
    assert seen["url"] == "https://aclanthology.org/2025.emnlp-main.1640.pdf"
    assert seen["cache_key"] == "p1"
    assert seen["cache_dir"] == site / "cache" / "pdf_text"
    assert "[Full PDF text]" in content
    assert "REMOTE_PDF_SENTINEL" in content


def test_build_chat_messages_for_library_uses_related_papers(tmp_path: Path):
    messages = build_chat_messages(
        _site(tmp_path),
        question="BBQ fairness 有哪些论文？",
        paper_key=None,
        mode="library",
        allowed_roots=[tmp_path],
    )

    assert "Related library papers" in messages[1]["content"]
    assert "Bias Benchmark" in messages[1]["content"]


def test_generate_chat_response_uses_injected_openai_compatible_client(tmp_path: Path):
    site = _site(tmp_path)
    state = tmp_path / ".reader"
    registry = ReaderModelRegistry(state)
    registry.upsert_provider(
        ModelProvider(
            id="test-provider",
            label="Test",
            base_url="https://llm.example.com/v1",
            models=["test-model"],
            default_model="test-model",
        )
    )
    registry.set_provider_key("test-provider", "sk-test")
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)

            class Message:
                content = "这是回答"

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    result = generate_chat_response(
        registry=registry,
        site_dir=site,
        payload={"provider_id": "test-provider", "model": "test-model", "question": "贡献？", "paper_key": "p1"},
        allowed_roots=[tmp_path],
        client_factory=FakeClient,
    )

    assert result["answer"] == "这是回答"
    assert result["provider_id"] == "test-provider"
    assert calls[0]["client"] == {"base_url": "https://llm.example.com/v1", "api_key": "sk-test"}
    assert calls[1]["model"] == "test-model"
    assert calls[1]["messages"][1]["content"].count("Bias Benchmark") == 1
