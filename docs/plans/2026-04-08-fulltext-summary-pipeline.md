# Full-Text Paper Summarization Pipeline Plan

> For Hermes: implement this before re-enabling any summary cron jobs.

**Goal:** Summarize papers only after fetching and reading full paper text/PDF, then write the summary back to Notion.

**Architecture:** Keep discovery/sync unchanged, then add a second-stage enrichment pipeline: Notion URL -> canonical PDF/fulltext fetch -> local cache -> text extraction -> summary -> Notion update. Prefer arXiv and ACL direct PDF routes first; for Scholar use the stored URL and fall back to arXiv/ACL patterns when possible.

**Tech Stack:** Python, notion-client, requests, PyMuPDF/pymupdf4llm or web extraction fallback, existing OpenRouter summarizer.

---

## Confirmed facts from current system

- Repo: `/home/orange/paper-search`
- Topic config: `/home/orange/paper-search/topics.json`
- Current paper entries already have strong URL coverage:
  - ACL: 100% URL coverage in all 3 topics checked
  - arXiv: 100% URL coverage in all 3 topics checked
  - Scholar: 100% URL coverage in all 3 topics checked
- Current repo does **not** yet include PDF/fulltext extraction code.
- Current repo venv is missing PDF extraction libs (`pymupdf`, `pymupdf4llm`, `bs4`, etc.).

---

## Proposed local storage layout

Create under repo root:

- `/home/orange/paper-search/cache/pdfs/` — downloaded PDFs
- `/home/orange/paper-search/cache/fulltext/` — extracted text / markdown
- `/home/orange/paper-search/cache/meta/` — per-paper metadata / fetch status

Use stable filenames derived from URL hash or page id.

---

## Task 1: Add dependency support for full-text extraction

**Files:**
- Modify: `/home/orange/paper-search/pyproject.toml`
- Create: `/home/orange/paper-search/paper_search/fulltext.py`

**Implementation:**
- Add dependencies for:
  - `pymupdf`
  - `pymupdf4llm`
  - `beautifulsoup4`
- Keep `requests` as the fetch layer.

**Verification:**
- Fresh venv install succeeds.
- `python -c "import pymupdf, pymupdf4llm, bs4"` passes.

---

## Task 2: Build URL -> canonical PDF resolver

**Files:**
- Create: `/home/orange/paper-search/paper_search/fulltext.py`
- Test: `/home/orange/paper-search/tests/test_fulltext.py`

**Implementation:**
- Add helpers:
  - `resolve_pdf_url(url: str) -> str | None`
  - arXiv abs -> pdf mapping
  - ACL Anthology paper URL -> `.pdf` mapping
  - direct `.pdf` passthrough
  - Scholar URLs that already point to arXiv should resolve to arXiv PDF
- If no PDF is derivable, keep original URL for HTML extraction fallback.

**Verification:**
- arXiv URL resolves to `/pdf/...pdf`
- ACL Anthology URL resolves to `.pdf`
- non-PDF URL returns original/fallback candidate

---

## Task 3: Add local cache management

**Files:**
- Create: `/home/orange/paper-search/paper_search/fulltext.py`

**Implementation:**
- Add functions:
  - `paper_cache_key(url: str) -> str`
  - `pdf_cache_path(url: str) -> Path`
  - `text_cache_path(url: str) -> Path`
  - `meta_cache_path(url: str) -> Path`
- Cache downloads locally before extraction.
- Store fetch metadata including source URL, resolved URL, fetch timestamp, extraction status.

**Verification:**
- Same URL maps to same cache paths.
- Cache directories auto-create.

---

## Task 4: Download and extract full text

**Files:**
- Create: `/home/orange/paper-search/paper_search/fulltext.py`

**Implementation:**
- Add:
  - `download_document(url: str, resolved_url: str | None = None) -> Path`
  - `extract_full_text(path: Path) -> str`
  - `get_full_text(url: str) -> dict`
- Preferred order:
  1. Resolve PDF URL
  2. Download PDF to local cache
  3. Extract text with PyMuPDF/PyMuPDF4LLM
  4. If PDF path is unavailable, try HTML fetch + BeautifulSoup fallback
- Return structured data like:
  - `{"mode": "pdf"|"html", "text": ..., "source_url": ..., "resolved_url": ..., "cache_path": ...}`

**Verification:**
- arXiv sample returns substantial extracted text
- ACL sample returns substantial extracted text
- text length threshold check (e.g. >3000 chars) for successful fulltext extraction

---

## Task 5: Add summary-from-fulltext function

**Files:**
- Modify: `/home/orange/paper-search/paper_search/summarizer.py`

**Implementation:**
- Keep current abstract-based helper for fallback/manual use.
- Add new function:
  - `summarize_full_text(title: str, full_text: str, max_retries: int = 5) -> str`
- Prompt must explicitly instruct the model that it is summarizing from the paper body/full text, not only title/abstract.
- For long documents, truncate or chunk intelligently (e.g. first N characters plus intro/method/result sections if detectable).

**Verification:**
- A real arXiv paper can produce a structured summary.
- Summary clearly reflects content beyond the title alone.

---

## Task 6: Add Notion full-text enrichment worker

**Files:**
- Create: `/home/orange/paper-search/paper_search/fulltext_pipeline.py`

**Implementation:**
- Read `topics.json`
- Iterate topic databases across ACL/arXiv/Scholar
- For each page:
  - require URL
  - skip if Summary already exists
  - fetch full text
  - summarize from full text
  - update Notion `Summary`
- Optional future properties if schema allows:
  - `Full Text Status`
  - `Local Cache Path`
  - `Resolved PDF URL`

**Verification:**
- One page can be processed end-to-end.
- Failed fetches are skipped cleanly and logged.

---

## Task 7: Add CLI entrypoints

**Files:**
- Modify: `/home/orange/paper-search/paper_search/cli.py`

**Implementation:**
- Add commands like:
  - `paper-search summarize-fulltext <topic_slug>`
  - `paper-search summarize-fulltext <topic_slug> --source acl`
  - `paper-search summarize-fulltext <topic_slug> --limit 10`
- These commands should only process already-synced Notion items and use full text.

**Verification:**
- Dry run / small limit works from CLI.

---

## Task 8: Replace old abstract-only cron workflow

**Files:**
- No repo file change required; update Hermes cron jobs after CLI works.

**Implementation:**
- Keep search/sync cron jobs.
- Replace abstract-only summary cron with a fulltext-only batch job.
- Batch limit should remain bounded (e.g. 10-20 papers/run) for free models.

**Verification:**
- One cron run summarizes at least one paper from fetched full text.

---

## Important notes

- Yes, local storage is the right approach first. Cache PDFs/full text locally, then summarize from the cached copy.
- Notion API access does **not** expose workspace storage quota/usage in the current integration path. Storage should be checked in the Notion web UI / workspace settings, not via the current API-based workflow.
- Since your Notion entries already have URLs at effectively 100% coverage across ACL/arXiv/Scholar, the URL side is in good shape for this pipeline.
