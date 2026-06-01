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


def test_public_profile_redacts_private_fields_and_token_like_values(tmp_path: Path):
    papers = [
        ReaderPaper(
            paper_id="p-secret",
            title="Safe Public Paper",
            source_url="https://arxiv.org/abs/2601.00001?token=abc123SECRET",
            notion_url="https://notion.so/private-page",
            summary="This summary accidentally mentions NOTION_" + "TOKEN=super-secret-value and /home/orange/private.pdf",
            obsidian_note="/home/orange/Documents/Obsidian Vault/Papers/private.md",
            local_fulltext="/home/orange/paper-search/cache/fulltext/private.md",
            local_document="/home/orange/papers/private.pdf",
            tags=["bias"],
        )
    ]

    render_site(papers, tmp_path, site_title="Public Reader", profile="public")

    all_text = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.html"))
    metadata = (tmp_path / "data" / "papers.json").read_text(encoding="utf-8")
    combined = all_text + metadata

    assert "notion.so" not in combined
    assert "Obsidian Vault" not in combined
    assert "/home/orange" not in combined
    assert "super-secret-value" not in combined
    assert "token" + "=" not in combined
    assert "https://arxiv.org/abs/2601.00001" in combined


def test_private_profile_keeps_local_assets_and_deep_sections(tmp_path: Path):
    papers = [
        ReaderPaper(
            paper_id="deep-paper",
            title="Deep Bias Evaluation",
            authors=["Alice"],
            topic_slug="bias-fairness",
            source_label="ACL",
            source_url="https://aclanthology.org/2026.deep-bias/",
            notion_url="https://notion.so/deep-paper",
            obsidian_note="/vault/Bias/Deep Bias Evaluation.md",
            local_fulltext="/vault/fulltext/deep.md",
            local_document="/vault/pdfs/deep.pdf",
            zh_brief="中文速览内容",
            tldr="One sentence TLDR",
            motivation="Why this matters",
            method="Benchmark construction",
            results="Model bias increased",
            limitations="Small language set",
            relevance="Useful for MultilingualBBQ",
            notebooklm_audio="/vault/audio/deep-dive.mp3",
        )
    ]

    render_site(papers, tmp_path, site_title="Private Reader", profile="private")
    detail = (tmp_path / "papers" / "deep-paper.html").read_text(encoding="utf-8")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert "Deep Sections" in index
    assert "TL;DR" in detail
    assert "Motivation / 研究动机" in detail
    assert "Method / 方法" in detail
    assert "Results / 结果" in detail
    assert "Limitations / 局限" in detail
    assert "Why relevant to Sidney PhD / 与我的博士相关性" in detail
    assert "/vault/Bias/Deep Bias Evaluation.md" in detail
    assert "/vault/audio/deep-dive.mp3" in detail


def test_public_profile_sanitizes_lists_embedded_private_urls_and_stale_private_files(tmp_path: Path):
    stale_dir = tmp_path / "papers"
    stale_dir.mkdir()
    (stale_dir / "old-private.html").write_text("/home/orange secret https://notion.so/private", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "old.json").write_text("/vault/private", encoding="utf-8")

    papers = [
        ReaderPaper(
            paper_id="public-edge",
            title="Public Edge Case",
            authors=["Alice", "/vault/private-author", "Bearer sk-test-secret"],
            tags=["bias", "Obsidian Vault/private-tag", "API_KEY: abc123SECRET"],
            source_url="https://notion.so/private-source?token=abc",
            summary="See https://notion.so/private-page and /vault/private.md plus Authorization: Bearer sk-secret-value",
            tldr='{"OPENROUTER_API_KEY": "sk-secret-value"}',
        )
    ]

    render_site(papers, tmp_path, site_title="Public Reader", profile="public")

    assert not (tmp_path / "papers" / "old-private.html").exists()
    assert not (tmp_path / "data" / "old.json").exists()

    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix in {".html", ".json", ".js", ".css"}
    )
    assert "notion.so" not in combined
    assert "/vault" not in combined
    assert "Obsidian Vault" not in combined
    assert "sk-secret-value" not in combined
    assert "abc123SECRET" not in combined
    assert "Bearer" not in combined


def test_public_profile_rejects_unsafe_source_url_scheme(tmp_path: Path):
    papers = [ReaderPaper(paper_id="bad-url", title="Bad URL", source_url="javascript:alert(1)")]

    render_site(papers, tmp_path, site_title="Public Reader", profile="public")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.html"))

    assert "javascript:" not in combined


def test_public_profile_redacts_json_secret_notion_variants_and_windows_paths(tmp_path: Path):
    papers = [
        ReaderPaper(
            paper_id="edge-redaction",
            title="Edge Redaction",
            summary='{"OPENROUTER_API_KEY": "topsecret123"} https://workspace.notion.so/private C:\\Users\\orange\\secret.pdf C:/Users/orange/secret.pdf https://abc.notion.site/private',
            tags=['PASSWORD: topsecret456'],
        )
    ]

    render_site(papers, tmp_path, site_title="Public Reader", profile="public")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix in {".html", ".json"}
    )

    assert "topsecret123" not in combined
    assert "topsecret456" not in combined
    assert "notion.so" not in combined
    assert "notion.site" not in combined
    assert "C:\\Users" not in combined
    assert "C:/Users" not in combined
    assert "OPENROUTER_API_KEY" not in combined
    assert "PASSWORD" not in combined


def test_public_profile_redacts_bare_notion_domains_exact_local_markers_and_root_stale_html(tmp_path: Path):
    (tmp_path / "old-private.html").write_text("/home/orange https://notion.so private", encoding="utf-8")
    papers = [
        ReaderPaper(
            paper_id="more-redaction",
            title="More Redaction",
            summary="https://notion.so https://workspace.notion.so https://notion.site /vault/ C:\\secret\\file.txt file:///home/orange/private.pdf GITHUB_TOKEN: topsecret789",
        )
    ]

    render_site(papers, tmp_path, site_title="Public Reader", profile="public")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix in {".html", ".json"}
    )

    assert not (tmp_path / "old-private.html").exists()
    assert "notion.so" not in combined
    assert "notion.site" not in combined
    assert "/vault" not in combined
    assert "C:\\secret" not in combined
    assert "file:///" not in combined
    assert "GITHUB_TOKEN" not in combined
    assert "topsecret789" not in combined


def test_link_renderer_rejects_control_character_urls(tmp_path: Path):
    papers = [ReaderPaper(paper_id="bad-control", title="Bad Control", source_url="http://example.com\njavascript:alert(1)")]

    render_site(papers, tmp_path, site_title="Reader", profile="private")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.html"))

    assert "http://example.com" not in combined
    assert "javascript:" not in combined


def test_private_profile_does_not_emit_unsafe_href_schemes(tmp_path: Path):
    papers = [
        ReaderPaper(
            paper_id="private-bad-url",
            title="Private Bad URL",
            source_url="javascript:alert(1)",
            notion_url="data:text/html,boom",
        )
    ]

    render_site(papers, tmp_path, site_title="Private Reader", profile="private")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.html"))

    assert "javascript:" not in combined
    assert "data:text/html" not in combined
