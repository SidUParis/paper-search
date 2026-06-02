from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_search.reader_notes import build_append_note_blocks, save_note_to_notion, update_reading_status


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


def _make_site(tmp_path: Path, paper_updates: dict | None = None) -> Path:
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    paper = {
        "paper_id": "notion-page-1",
        "title": "Bias Benchmark Paper",
        "topic_slug": "bias-fairness",
        "source_label": "ACL",
    }
    if paper_updates:
        paper.update(paper_updates)
    (site / "data" / "papers.json").write_text(json.dumps([paper]), encoding="utf-8")
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


def test_update_reading_status_writes_notion_status_and_local_metadata(tmp_path: Path):
    site = _make_site(tmp_path)
    client = FakeNotionClient()

    result = update_reading_status(
        site_dir=site,
        payload={"paper_key": "notion-page-1", "status": "read"},
        notion_client=client,
    )

    assert result["ok"] is True
    assert result["reading_status"] == "Read"
    call = client.pages.update_calls[0]
    assert call["page_id"] == "notion-page-1"
    assert call["properties"] == {"Status": {"select": {"name": "Read"}}}
    papers = json.loads((site / "data" / "papers.json").read_text(encoding="utf-8"))
    assert papers[0]["status"] == "Read"
    assert papers[0]["reading_status"] == "Read"


def test_update_reading_status_syncs_obsidian_frontmatter_without_touching_body(tmp_path: Path):
    note_path = tmp_path / "vault" / "papers" / "bias-benchmark-paper.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        "title: Bias Benchmark Paper\n"
        "status: active\n"
        "reading_status: To Read\n"
        "review_status: summarized\n"
        "---\n"
        "\n"
        "# Manual note body\n"
        "Keep my handwritten synthesis.\n",
        encoding="utf-8",
    )
    site = _make_site(tmp_path, {"obsidian_note": str(note_path)})
    client = FakeNotionClient()

    result = update_reading_status(
        site_dir=site,
        payload={"paper_key": "notion-page-1", "status": "read"},
        notion_client=client,
    )

    text = note_path.read_text(encoding="utf-8")
    assert result["obsidian_synced"] is True
    assert result["obsidian_note"] == str(note_path)
    assert "reading_status: Read" in text
    assert "notion_status: Read" in text
    assert "status: active" in text
    assert "review_status: summarized" in text
    assert "# Manual note body" in text
    assert "Keep my handwritten synthesis." in text


def test_update_reading_status_rejects_unknown_status(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported_reading_status"):
        update_reading_status(
            site_dir=_make_site(tmp_path),
            payload={"paper_key": "notion-page-1", "status": "skimmed"},
            notion_client=FakeNotionClient(),
        )

