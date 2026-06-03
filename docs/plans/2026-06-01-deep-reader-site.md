# Deep Reader Site Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a GitHub Pages / static-site reader for the user's paper library, borrowing the Daily Paper Reader interaction model while keeping Notion as source-of-truth, paper-search as backend, and Obsidian as durable local asset/note layer.

**Architecture:** Add a `paper_search.reader_site` module that queries existing Notion topic data sources, enriches each paper with local Obsidian/cache/fulltext metadata when available, and exports a static `reader-site/` directory. The first milestone is a no-API static exporter using existing Notion records and Obsidian paths; later milestones add richer UI, GitHub Pages deployment, daily automation, and optional reuse of Daily Paper Reader frontend components.

**Tech Stack:** Python stdlib + existing Notion client helpers, Click CLI, static HTML/CSS/JS, optional GitHub Pages deployment via generated docs/site artifacts.

---

## Design Decisions

1. **Notion remains source-of-truth** for paper metadata and status.
2. **paper-search remains the data pipeline** for crawling, full-text extraction, summarization, Qwen/DeepSeek precompute, and Notion writeback.
3. **Obsidian remains the durable local research layer** for PDFs, fulltext markdown, notes, graph links, and thesis-specific annotations.
4. **Reader Site is a presentation/export layer**, not a competing database.
5. **Static output must be safe to publish**: default pages expose titles/abstracts/summaries/links, but local absolute paths are shown only as metadata text unless explicitly enabled later.
6. **Daily Paper Reader is a UI/structure reference**, not a hard dependency for the first milestone.

---

## Task 1: Add reader-site data model and HTML renderer

**Objective:** Create a small, testable static-site renderer independent of live Notion calls.

**Files:**
- Create: `paper_search/reader_site.py`
- Test: `tests/test_reader_site.py`

**Implementation notes:**
- Define `ReaderPaper` dataclass with fields: `paper_id`, `title`, `authors`, `year`, `venue`, `topic_slug`, `source_label`, `source_url`, `notion_url`, `abstract`, `summary`, `zh_brief`, `obsidian_note`, `local_fulltext`, `local_document`, `tags`, `status`, `updated_at`.
- Add `slugify`, `paper_slug`, and `render_site(papers, output_dir, site_title=...)`.
- Output files:
  - `index.html`
  - `assets/style.css`
  - `assets/app.js`
  - `papers/<paper-slug>.html`
  - `data/papers.json`
- UI should include left sidebar, search box, topic/source filters, paper cards, and detail pages.

**Verification:**
- Unit tests create two fake papers and assert all expected files exist.
- Assert `index.html` links to paper detail pages.
- Assert HTML escaping prevents raw `<script>` injection.

---

## Task 2: Add Notion collector for topic data sources

**Objective:** Convert existing Notion page objects into `ReaderPaper` records.

**Files:**
- Modify: `paper_search/reader_site.py`
- Test: `tests/test_reader_site.py`

**Implementation notes:**
- Reuse parsing conventions from `fulltext_pipeline.py`.
- Add pure helpers: `_text_content`, `_title_content`, `_authors_content`, `_year_from_props`, `_select_name`, `_multi_select_names`, `reader_paper_from_notion_page(...)`.
- Do not require live Notion for unit tests.

**Verification:**
- Test a fake Notion page with `Title`, `Authors`, `URL`, `Abstract`, `Summary`, `Published`, `Status`, `Topics`, `Venue`.
- Assert fields map correctly.

---

## Task 3: Add CLI command `export-reader-site`

**Objective:** Let the user generate the static reader from existing Notion databases.

**Files:**
- Modify: `paper_search/cli.py`
- Modify: `paper_search/reader_site.py`
- Test: `tests/test_reader_site.py` or CLI smoke if practical

**Command shape:**
```bash
paper-search export-reader-site --topic all --source all --output reader-site --limit 200
paper-search export-reader-site --topic bias-fairness --source all --output reader-site --limit 100
```

**Implementation notes:**
- Load topics from `topics.json`.
- For each configured topic/source data source, query Notion pages with pagination.
- Convert to `ReaderPaper` and render static site.
- Print JSON-ish summary: output path, number of papers, topic/source breakdown.

**Verification:**
- `python -m py_compile paper_search/reader_site.py paper_search/cli.py`
- `pytest tests/test_reader_site.py -q`

---

## Task 4: Enrich site with Obsidian/local asset linking

**Objective:** Surface the deep local research layer without duplicating data.

**Files:**
- Modify: `paper_search/reader_site.py`
- Test: `tests/test_reader_site.py`

**Implementation notes:**
- Map known Obsidian export conventions from `obsidian_export.py`.
- If a Notion page has a matching generated Obsidian note path in existing metadata/caches, include it.
- First milestone can expose `obsidian_note`, `local_fulltext`, and `local_document` from explicit fields when available; later add robust lookup.

**Verification:**
- Tests ensure local asset fields appear on detail pages when present.

---

## Task 5: Add GitHub Pages deployment option

**Objective:** Make the generated site readable from any device/platform.

**Files:**
- Create: `.github/workflows/export-reader-site.yml` or document manual deployment in `docs/reader-site.md`
- Create/modify: `docs/reader-site.md`

**Implementation notes:**
- Start local-first: generate to `reader-site/` and optionally copy to a publish branch/repo.
- Avoid committing private cache/PDF/fulltext assets by default.
- Deployment repository can be `SidUParis/paper-search-reader` or GitHub Pages in `paper-search`; choose after initial local static site works.

**Verification:**
- Build command completes.
- Generated `index.html` opens locally.
- No private `.env`, cache directories, or raw PDFs are committed.

---

## Future Milestones

- Borrow Daily Paper Reader's stronger UI interactions: color bookmarks, keyboard previous/next, share buttons, metadata JSON download.
- Add password/private mode if the site exposes non-public notes.
- Add topic dashboards for BBQ / multilingual BBQ / fairness / sycophancy / summarization.
- Add daily cron that refreshes Notion, regenerates site, and pushes GitHub Pages.
- Add NotebookLM audio/deep-dive links per paper when available.
