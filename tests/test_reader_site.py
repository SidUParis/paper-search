from pathlib import Path

from paper_search.reader_site import ReaderPaper, reader_paper_from_notion_page, render_site, slugify


def test_slugify_ascii_fallback():
    assert slugify("Attention Is All You Need!") == "attention-is-all-you-need"
    assert slugify("知识图谱") == "item"


def test_reader_paper_from_notion_page_maps_common_properties():
    page = {
        "id": "page-123",
        "url": "https://notion.so/page-123",
        "last_edited_time": "2026-06-01T00:00:00.000Z",
        "properties": {
            "Title": {"title": [{"plain_text": "Bias Benchmark"}]},
            "Authors": {"rich_text": [{"plain_text": "Alice A, Bob B"}]},
            "URL": {"url": "https://arxiv.org/abs/2601.00001"},
            "Abstract": {"rich_text": [{"plain_text": "Abstract text"}]},
            "Summary": {"rich_text": [{"plain_text": "Summary text"}]},
            "Published": {"date": {"start": "2026-01-02"}},
            "Status": {"select": {"name": "Reading"}},
            "Topics": {"multi_select": [{"name": "fairness"}, {"name": "BBQ"}]},
            "Venue": {"select": {"name": "ACL"}},
        },
    }

    paper = reader_paper_from_notion_page(page, topic_slug="bias-fairness", source_label="ACL")

    assert paper.paper_id == "page-123"
    assert paper.title == "Bias Benchmark"
    assert paper.authors == ["Alice A", "Bob B"]
    assert paper.source_url == "https://arxiv.org/abs/2601.00001"
    assert paper.year == "2026"
    assert paper.status == "Reading"
    assert paper.tags == ["fairness", "BBQ"]
    assert paper.venue == "ACL"


def test_render_site_writes_index_detail_assets_and_escapes_html(tmp_path: Path):
    papers = [
        ReaderPaper(
            paper_id="p1",
            title="<script>alert(1)</script> Bias Paper",
            authors=["Alice"],
            year="2026",
            venue="ACL",
            topic_slug="bias-fairness",
            source_label="ACL",
            source_url="https://example.com/p1",
            notion_url="https://notion.so/p1",
            abstract="Abstract <b>not html</b>",
            summary="**RQ**: summary",
            zh_brief="中文简述",
            tags=["fairness"],
        ),
        ReaderPaper(
            paper_id="p2",
            title="Multilingual BBQ",
            topic_slug="bias-fairness",
            source_label="arxiv",
            summary="second summary",
            local_fulltext="/vault/papers/fulltext/p2.md",
            local_document="/vault/papers/pdfs/p2.pdf",
        ),
    ]

    summary = render_site(papers, tmp_path, site_title="Test Reader")

    assert summary["papers"] == 2
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "assets" / "style.css").exists()
    assert (tmp_path / "assets" / "app.js").exists()
    assert (tmp_path / "data" / "papers.json").exists()
    assert (tmp_path / "papers" / "p1.html").exists()
    assert (tmp_path / "papers" / "p2.html").exists()

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    detail = (tmp_path / "papers" / "p1.html").read_text(encoding="utf-8")
    detail2 = (tmp_path / "papers" / "p2.html").read_text(encoding="utf-8")

    assert "papers/p1.html" in index
    assert "papers/p2.html" in index
    assert "<script>alert(1)</script>" not in index
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail
    assert "/vault/papers/fulltext/p2.md" in detail2
