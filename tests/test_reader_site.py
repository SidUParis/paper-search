from pathlib import Path

import paper_search.reader_site as reader_site
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
            "Projects": {"multi_select": [{"name": "FrenchBBQ"}, {"name": "Social Science Readings"}]},
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
    assert paper.projects == ["FrenchBBQ", "Social Science Readings"]


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
    assert (tmp_path / "assets" / "xfair-logo.png").exists()
    assert (tmp_path / "data" / "papers.json").exists()
    assert (tmp_path / "papers" / "p1.html").exists()
    assert (tmp_path / "papers" / "p2.html").exists()

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    detail = (tmp_path / "papers" / "p1.html").read_text(encoding="utf-8")
    detail2 = (tmp_path / "papers" / "p2.html").read_text(encoding="utf-8")
    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")

    assert "paper.html?id=" in app_js
    assert "data/daily-featured.json" in app_js
    assert "Featured from daily digest" in app_js
    assert "https://www.xfairllm.com/" in app_js
    assert "XFaiR LLM logo" in app_js
    assert "xfair-logo.png" in app_js
    assert "Back to xfairllm.com" in app_js
    assert "papers/p1.html" not in index
    assert "papers/p2.html" not in index
    assert "<script>alert(1)</script>" not in index
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail
    assert "/vault/papers/fulltext/p2.md" in detail2


def test_render_site_adds_global_ai_terminal(tmp_path: Path):
    papers = [ReaderPaper(paper_id="p1", title="Bias Paper", summary="Summary")]

    render_site(papers, tmp_path, site_title="Test Reader")

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    ai = (tmp_path / "ai.html").read_text(encoding="utf-8")
    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")
    assert "AI Reader" in index
    assert "AI Reader" in ai
    assert "xfair-logo.png" in ai
    assert "XFaiR LLM logo" in ai
    assert "ai-side-nav" in ai
    assert "<span>01</span>Discovery" in ai
    assert "<span>03</span>AI Reader" in ai
    assert "Unify AI Reader chrome" in (tmp_path / "assets" / "style.css").read_text(encoding="utf-8")
    assert "id=\"chat-form\"" in ai
    assert "note-save-card" not in ai
    assert "Save current AI answer" not in ai
    assert "mini-send" in ai
    assert "chat-file-input" in ai
    assert "web-search-toggle" in ai
    assert "chat-model-preset" in ai
    assert "DeepSeek v4 flash" in ai  # static fallback until /api/models loads chat.xfairllm.com presets
    assert "composer-control-row" in ai
    assert "web-search-icon" in ai
    assert "aria-label=\"Attach temporary session file\"" in ai
    assert "🤖" not in ai
    assert "fetch('/api/chat'" in app_js
    assert "state.paper?'full_pdf':'library'" in app_js
    assert "max_fulltext_chars:200000" in app_js
    assert "/paper-assets/pdf/" in app_js
    assert "/paper-assets/pdf-page/" in app_js
    assert "/pdf-info" in app_js
    assert "loadModelPresets" in app_js
    assert "fetch('/api/models'" in app_js
    assert "cfg.presets" in app_js
    assert "chat_value" in app_js
    assert "attachments:state.uploadedFiles" in app_js
    assert "web_search:state.webSearch" in app_js
    assert "detectNotionIntent" in app_js
    assert "confirm-note-save" in app_js
    assert "fetch('/api/notes/save'" in app_js
    assert "pdf-zoom-in" in ai
    assert "pdf-zoom-out" in ai
    assert "pdf-annotate-toggle" not in ai
    assert "pdf-annotation-layer" not in ai
    assert "AI Assisted Reading" in ai
    assert "Contextual Chat" not in ai
    assert "zoomPdf" in app_js
    assert "togglePdfAnnotation" not in app_js
    assert "savePdfAnnotation" not in app_js
    assert "localStorage.setItem(pdfAnnotationKey" not in app_js
    assert "addThinkingBubble" in app_js
    assert "removeThinkingBubble" in app_js
    assert "model-thinking" in app_js
    assert "Research Projects" in ai
    assert "Research Topics" in ai
    assert "Venues" in ai
    assert "taxonomy-submenu" not in ai
    assert "reading-queue" not in ai
    assert "READING QUEUE" not in ai
    assert "paperProjects" in app_js
    assert "taxonomyMode" in app_js
    assert "selectTaxonomy" in app_js
    assert "inlineTaxonomySubmenu" in app_js
    assert "renderTaxonomySubmenu" not in app_js
    assert "Areas" not in ai


def test_render_site_preserves_cached_private_notebooklm_audio(tmp_path: Path, monkeypatch):
    papers = [ReaderPaper(paper_id="p1", title="Audio Paper", summary="Summary")]
    monkeypatch.setattr(reader_site, "_cached_notebooklm_audio_path", lambda paper_id: "cache/notebooklm_audio/p1_notebooklm-deepdive.mp3")

    render_site(papers, tmp_path, site_title="Test Reader", profile="private")

    data = (tmp_path / "data" / "papers.json").read_text(encoding="utf-8")
    assert "cache/notebooklm_audio/p1_notebooklm-deepdive.mp3" in data


def test_ai_reader_exposes_pdf_notes_and_extracted_figures(tmp_path: Path):
    papers = [ReaderPaper(paper_id="p1", title="Bias Paper", summary="Summary")]

    render_site(papers, tmp_path, site_title="Test Reader")

    ai = (tmp_path / "ai.html").read_text(encoding="utf-8")
    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")

    assert "reading-note-editor" in ai
    assert "figure-gallery" in ai
    assert "Use in chat" in app_js
    assert "selectedVisual" in app_js
    assert "reading_note" in app_js
    assert "extract-current-figures" in ai
    assert "/api/figures/extract" in app_js


def test_ai_reader_exposes_notebooklm_audio_tab(tmp_path: Path):
    papers = [ReaderPaper(paper_id="p1", title="Bias Paper", notebooklm_audio="https://example.com/audio.mp3")]

    render_site(papers, tmp_path, site_title="Test Reader")

    ai = (tmp_path / "ai.html").read_text(encoding="utf-8")
    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")

    assert "show-audio" in ai
    assert "audio-player-card" in ai
    assert "NotebookLM Audio" in ai
    assert "function audioUrl" in app_js
    assert "<audio controls" in app_js
    assert "/paper-assets/audio/" in app_js
    assert "Generate NotebookLM deep dive" in app_js
    assert "notebooklm-audio" in app_js


def test_ai_reader_opens_figures_in_zoomable_lightbox_not_download_links(tmp_path: Path):
    papers = [
        ReaderPaper(
            paper_id="p1",
            title="Bias Paper",
            summary="Summary",
            figures=[{"kind": "image", "title": "Figure 1", "src": "assets/paper-assets/p1/figure.webp"}],
        )
    ]

    render_site(papers, tmp_path, site_title="Test Reader")

    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")
    css = (tmp_path / "assets" / "style.css").read_text(encoding="utf-8")

    assert "openFigureViewer" in app_js
    assert "data-open-visual" in app_js
    assert "viewer-zoom-in" in app_js
    assert "viewer-next" in app_js
    assert "viewer-prev" in app_js
    assert "figure-viewer" in css
    assert "bottom" in css
    assert "target=\"_blank\" rel=\"noreferrer\"><img" not in app_js


def test_reader_stylesheet_is_not_line_numbered_or_truncated(tmp_path: Path):
    papers = [ReaderPaper(paper_id="p1", title="Bias Paper", summary="Summary")]

    render_site(papers, tmp_path, site_title="Test Reader")

    css = (tmp_path / "assets" / "style.css").read_text(encoding="utf-8")
    assert not css.startswith("     1|")
    assert "[truncated]" not in css
    assert css.lstrip().startswith("@import")
    assert ".reader-app" in css
    assert ".figure-viewer" in css
    assert "AI Reader right panel color unification" in css
    assert ".paper-studio .chat-starters .prompt-chip" in css
    assert "AI Reader center panel color unification" in css
    assert ".paper-studio .reading-note-panel" in css
    assert "grid-template-columns:1fr 1fr" in css
    assert ".paper-studio .paper-composer{grid-template-columns:minmax(0,1fr)!important" in css
    assert ".paper-studio .composer-control-row" in css
    assert ".paper-studio .composer-icon svg" in css
    assert "Main-site logo sync" in css
    assert ".brand-link .brand-logo" in css


def test_render_site_adds_per_paper_ask_panel_with_presets(tmp_path: Path):
    papers = [ReaderPaper(paper_id="p1", title="Bias Paper", summary="Summary")]

    render_site(papers, tmp_path, site_title="Test Reader")

    detail = (tmp_path / "papers" / "p1.html").read_text(encoding="utf-8")
    assert "Ask While Reading" in detail
    assert "data-paper-key=\"p1\"" in detail
    assert "中文讲解" in detail
    assert "和我的 PhD 关系" in detail
    assert "../assets/app.js?v=ai-reader-3" in detail


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

    assert (tmp_path / "library.html").exists()
    assert (tmp_path / "data" / "catalog.json").exists()
    assert "Library" in (tmp_path / "library.html").read_text(encoding="utf-8")
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


def test_private_render_site_extracts_pdf_images_into_gallery_assets(tmp_path: Path):
    import base64
    import json

    import pymupdf

    pdf_path = tmp_path / "source.pdf"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    doc = pymupdf.open()
    page = doc.new_page(width=220, height=180)
    page.insert_text((24, 32), "Table 1: Bias scores by language", fontsize=10)
    page.insert_image(pymupdf.Rect(40, 50, 140, 140), stream=png_bytes)
    doc.save(pdf_path)
    doc.close()

    render_site(
        [ReaderPaper(paper_id="p1", title="PDF Figure Paper", local_document=str(pdf_path))],
        tmp_path / "site",
        site_title="Private Reader",
        profile="private",
    )

    papers = json.loads((tmp_path / "site" / "data" / "papers.json").read_text(encoding="utf-8"))
    figures = papers[0]["figures"]
    assert figures
    assert figures[0]["kind"] == "image"
    assert figures[0]["src"].startswith("assets/paper-assets/p1/")
    assert (tmp_path / "site" / figures[0]["src"]).exists()
    assert "Figure & Table Gallery" in (tmp_path / "site" / "paper.html").read_text(encoding="utf-8")
    assert "renderFigureGallery" in (tmp_path / "site" / "assets" / "app.js").read_text(encoding="utf-8")


def test_public_render_site_does_not_expose_extracted_pdf_assets(tmp_path: Path):
    import base64
    import json

    import pymupdf

    pdf_path = tmp_path / "secret.pdf"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    doc = pymupdf.open()
    page = doc.new_page(width=120, height=120)
    page.insert_image(pymupdf.Rect(20, 20, 80, 80), stream=png_bytes)
    doc.save(pdf_path)
    doc.close()

    render_site(
        [ReaderPaper(paper_id="p-secret", title="Public PDF", local_document=str(pdf_path))],
        tmp_path / "public-site",
        site_title="Public Reader",
        profile="public",
    )

    papers = json.loads((tmp_path / "public-site" / "data" / "papers.json").read_text(encoding="utf-8"))
    assert papers[0]["figures"] == []
    assert not (tmp_path / "public-site" / "assets" / "paper-assets").exists()

def test_private_render_site_uses_existing_source_url_pdf_cache_for_gallery(tmp_path: Path, monkeypatch):
    import base64
    import json

    import pymupdf
    import paper_search.reader_site as reader_site

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(reader_site, "pdf_cache_path", lambda _url: cache_dir / "cached.pdf")
    cache_dir.mkdir()
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    doc = pymupdf.open()
    page = doc.new_page(width=120, height=120)
    page.insert_image(pymupdf.Rect(20, 20, 80, 80), stream=png_bytes)
    doc.save(cache_dir / "cached.pdf")
    doc.close()

    render_site(
        [ReaderPaper(paper_id="cached-paper", title="Cached PDF", source_url="https://arxiv.org/abs/2601.00001")],
        tmp_path / "site",
        site_title="Private Reader",
        profile="private",
    )

    papers = json.loads((tmp_path / "site" / "data" / "papers.json").read_text(encoding="utf-8"))
    assert papers[0]["figures"]


def test_render_site_adds_llm_find_bar_to_home_and_library(tmp_path: Path):
    render_site([ReaderPaper(paper_id="p1", title="Bias Paper", summary="Summary")], tmp_path, site_title="Test Reader")

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    library = (tmp_path / "library.html").read_text(encoding="utf-8")
    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")

    assert "Ask AI to find papers" in index
    assert "Ask AI to find papers" in library
    assert "id=\"rank-query\"" in index
    assert "fetch('/api/rank'" in app_js


def test_reader_source_filter_matches_venue_and_normalized_source(tmp_path: Path):
    render_site(
        [ReaderPaper(paper_id="p1", title="EMNLP Paper", source_label="ACL", venue="EMNLP", tags=["EMNLP"])],
        tmp_path,
        site_title="Test Reader",
    )

    app_js = (tmp_path / "assets" / "app.js").read_text(encoding="utf-8")

    assert "function sourceKey" in app_js
    assert "function paperSourceKeys" in app_js
    assert "paperSourceKeys(p).includes(source)" in app_js
    assert "sourceLabel(v)" in app_js
