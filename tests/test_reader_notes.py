from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_search.reader_notes import build_append_note_blocks, save_note_to_notion


class FakeBlocksChildren:
    def __init__(self) -> None:
        self.append_calls: list[dict] = []

    def append(self, **kwargs):
        self.append_calls.append(kwargs)
        return {"ok": True}


class FakeBlocks:
    def __init__(self) -> None:
        self.children = FakeBlocksChildren()


class FakePages:
    def __init__(self) -> None:
        self.update_calls: list[dict] = []

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"ok": True}


class FakeNotionClient:
    def __init__(self) -> None:
        self.blocks = FakeBlocks()
        self.pages = FakePages()


def _make_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "papers.json").write_text(
        json.dumps([
            {
                "paper_id": "notion-page-1",
                "title": "Bias Benchmark Paper",
                "topic_slug": "bias-fairness",
                "source_label": "ACL",
            }
        ]),
        encoding="utf-8",
    )
    return site


def test_build_append_note_blocks_contains_question_answer_and_destination():
    blocks = build_append_note_blocks(
        title="Bias Benchmark Paper",
        question="这篇文章和我的 PhD 有什么关系？",
        answer="它可以作为 MultilingualBBQ 的 related work。",
        destination="PhD Relevance",
    )

    text = json.dumps(blocks, ensure_ascii=False)
    assert "AI Reading Note" in text
    assert "Bias Benchmark Paper" in text
    assert "这篇文章和我的 PhD" in text
    assert "MultilingualBBQ" in text
    assert "PhD Relevance" in text


def test_save_note_to_notion_appends_to_page_body(tmp_path: Path):
    site = _make_site(tmp_path)
    client = FakeNotionClient()

    result = save_note_to_notion(
        site_dir=site,
        payload={
            "paper_key": "notion-page-1",
            "question": "方法是什么？",
            "answer": "方法是构造 benchmark 并评估 bias。",
            "destination": "AI Note",
            "mode": "append",
        },
        notion_client=client,
    )

    assert result["ok"] is True
    assert result["paper_id"] == "notion-page-1"
    assert result["mode"] == "append"
    assert client.blocks.children.append_calls
    call = client.blocks.children.append_calls[0]
    assert call["block_id"] == "notion-page-1"
    assert "方法是什么" in json.dumps(call["children"], ensure_ascii=False)


def test_save_note_to_notion_updates_allowed_property(tmp_path: Path):
    site = _make_site(tmp_path)
    client = FakeNotionClient()

    result = save_note_to_notion(
        site_dir=site,
        payload={
            "paper_key": "notion-page-1",
            "answer": "这篇文章和 multilingual bias evaluation 直接相关。",
            "destination": "PhD Relevance",
            "mode": "property",
        },
        notion_client=client,
    )

    assert result["ok"] is True
    assert result["mode"] == "property"
    assert client.pages.update_calls
    call = client.pages.update_calls[0]
    assert call["page_id"] == "notion-page-1"
    assert "PhD Relevance" in call["properties"]
    assert "multilingual bias" in json.dumps(call["properties"], ensure_ascii=False)


def test_save_note_to_notion_rejects_unknown_property(tmp_path: Path):
    site = _make_site(tmp_path)

    with pytest.raises(ValueError, match="unsupported_destination"):
        save_note_to_notion(
            site_dir=site,
            payload={"paper_key": "notion-page-1", "answer": "x", "destination": "API Key", "mode": "property"},
            notion_client=FakeNotionClient(),
        )
