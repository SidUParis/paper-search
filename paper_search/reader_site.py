"""Static reader-site export for the paper-search library.

This module is intentionally presentation-focused: Notion remains the
source-of-truth, Obsidian/local caches remain the durable asset layer, and the
reader site is a generated static view that can be published with GitHub Pages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
from typing import Any, cast
import unicodedata

from paper_search.notion_sync import get_notion_client
from paper_search.topics import load_topics


@dataclass(slots=True)
class ReaderPaper:
    """Normalized paper record for the static reader site."""

    paper_id: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: str = ""
    venue: str = ""
    topic_slug: str = ""
    source_label: str = ""
    source_url: str = ""
    notion_url: str = ""
    abstract: str = ""
    summary: str = ""
    zh_brief: str = ""
    obsidian_note: str = ""
    local_fulltext: str = ""
    local_document: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = ""
    updated_at: str = ""

    @property
    def display_year(self) -> str:
        return self.year or "Unknown"

    @property
    def display_venue(self) -> str:
        return self.venue or self.source_label or "Unknown"


def slugify(text: str, fallback: str = "item") -> str:
    """Return a URL-safe ASCII slug."""

    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or fallback


def paper_slug(paper: ReaderPaper) -> str:
    """Stable-ish detail-page slug for one paper."""

    base = paper.paper_id or paper.title
    slug = slugify(base, fallback="paper")
    if slug == "paper" and paper.notion_url:
        slug = slugify(paper.notion_url.rsplit("/", 1)[-1], fallback="paper")
    return slug


def _text_content(rich: list[dict] | None) -> str:
    if not rich:
        return ""
    parts: list[str] = []
    for item in rich:
        parts.append(item.get("plain_text") or item.get("text", {}).get("content", ""))
    return "".join(parts)


def _title_content(title_prop: dict | None) -> str:
    if not title_prop:
        return ""
    return _text_content(title_prop.get("title", []))


def _authors_content(prop: dict | None) -> list[str]:
    text = _text_content((prop or {}).get("rich_text", []))
    if not text:
        return []
    # Notion imports in this repo store authors as comma-separated rich text.
    return [part.strip() for part in text.split(",") if part.strip()]


def _year_from_props(props: dict) -> str:
    published = (props.get("Published", {}) or {}).get("date") or {}
    start = str(published.get("start") or "")
    return start[:4] if start else ""


def _select_name(prop: dict | None) -> str:
    select = (prop or {}).get("select") or {}
    return str(select.get("name") or "")


def _multi_select_names(prop: dict | None) -> list[str]:
    values = (prop or {}).get("multi_select") or []
    return [str(item.get("name") or "").strip() for item in values if str(item.get("name") or "").strip()]


def _first_existing_text_prop(props: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = _text_content((props.get(name, {}) or {}).get("rich_text", [])).strip()
        if value:
            return value
    return ""


def reader_paper_from_notion_page(
    page: dict,
    *,
    topic_slug: str,
    source_label: str,
) -> ReaderPaper:
    """Map a Notion page object into a `ReaderPaper`.

    The mapper is deliberately tolerant: some topic databases have `Venue`,
    some have `Source`, and richer local fields may be absent in older entries.
    """

    props = page.get("properties", {}) or {}
    title = _title_content(props.get("Title", {})).strip() or "Untitled paper"
    notion_url = str(page.get("url") or "")
    notion_id = str(page.get("id") or "")
    url = str((props.get("URL", {}) or {}).get("url") or "")
    venue = _select_name(props.get("Venue")) or _select_name(props.get("Source")) or source_label
    status = _select_name(props.get("Status"))
    tags = _multi_select_names(props.get("Topics"))
    abstract = _text_content((props.get("Abstract", {}) or {}).get("rich_text", [])).strip()
    summary = _text_content((props.get("Summary", {}) or {}).get("rich_text", [])).strip()
    zh_brief = _first_existing_text_prop(props, ("Chinese Brief", "ZH Brief", "中文简述", "Zh Brief"))
    obsidian_note = _first_existing_text_prop(props, ("Obsidian", "Obsidian Note", "Obsidian Path"))
    local_fulltext = _first_existing_text_prop(props, ("Local Fulltext", "Fulltext Path", "Local Full Text"))
    local_document = _first_existing_text_prop(props, ("Local PDF", "Local Document", "PDF Path"))
    updated_at = str(page.get("last_edited_time") or page.get("created_time") or "")

    paper_id = notion_id or slugify(title)
    return ReaderPaper(
        paper_id=paper_id,
        title=title,
        authors=_authors_content(props.get("Authors", {})),
        year=_year_from_props(props),
        venue=venue,
        topic_slug=topic_slug,
        source_label=source_label,
        source_url=url,
        notion_url=notion_url,
        abstract=abstract,
        summary=summary,
        zh_brief=zh_brief,
        obsidian_note=obsidian_note,
        local_fulltext=local_fulltext,
        local_document=local_document,
        tags=tags,
        status=status,
        updated_at=updated_at,
    )


def _topic_sources(topic: dict, source: str = "all") -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    if source in ("all", "acl") and topic.get("acl_data_source_id"):
        sources.append(("ACL", topic["acl_data_source_id"]))
    if source in ("all", "arxiv") and topic.get("arxiv_data_source_id"):
        sources.append(("arxiv", topic["arxiv_data_source_id"]))
    if source in ("all", "scholar") and topic.get("scholar_data_source_id"):
        sources.append(("Scholar", topic["scholar_data_source_id"]))
    return sources


def collect_reader_papers(
    *,
    topic_slug: str = "all",
    source: str = "all",
    limit: int | None = None,
) -> list[ReaderPaper]:
    """Collect reader papers from configured Notion data sources."""

    topics = load_topics()
    selected = topics.items() if topic_slug == "all" else [(topic_slug, topics.get(topic_slug))]
    notion = get_notion_client()
    papers: list[ReaderPaper] = []

    for slug, topic in selected:
        if not topic:
            raise ValueError(f"Topic '{slug}' not found")
        for label, data_source_id in _topic_sources(topic, source=source):
            cursor = None
            while True:
                kwargs = {"data_source_id": data_source_id, "page_size": 100}
                if cursor:
                    kwargs["start_cursor"] = cursor
                response = cast(dict[str, Any], notion.data_sources.query(**kwargs))
                for page in response.get("results", []):
                    papers.append(reader_paper_from_notion_page(page, topic_slug=slug, source_label=label))
                    if limit is not None and len(papers) >= limit:
                        return papers
                if not response.get("has_more"):
                    break
                cursor = response.get("next_cursor")
    return papers


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _paper_card(paper: ReaderPaper, href: str) -> str:
    tags = " ".join(f'<span class="tag">{escape(t)}</span>' for t in paper.tags[:8])
    summary = paper.zh_brief or paper.summary or paper.abstract
    return f"""
    <article class="paper-card" data-topic="{escape(paper.topic_slug)}" data-source="{escape(paper.source_label)}" data-year="{escape(paper.year)}">
      <a class="paper-title" href="{escape(href)}">{escape(paper.title)}</a>
      <div class="meta">{escape(paper.display_year)} · {escape(paper.display_venue)} · {escape(paper.status or 'unclassified')}</div>
      <p>{escape(summary[:280])}{'…' if len(summary) > 280 else ''}</p>
      <div class="tags">{tags}</div>
    </article>
    """


def _detail_page(paper: ReaderPaper, site_title: str) -> str:
    authors = ", ".join(paper.authors)
    tags = " ".join(f'<span class="tag">{escape(t)}</span>' for t in paper.tags)

    def link(label: str, url: str) -> str:
        if not url:
            return ""
        safe = escape(url, quote=True)
        return f'<li><a href="{safe}" target="_blank" rel="noreferrer">{escape(label)}</a></li>'

    local_assets = "".join(
        item
        for item in [
            f"<li>Obsidian note: <code>{escape(paper.obsidian_note)}</code></li>" if paper.obsidian_note else "",
            f"<li>Local fulltext: <code>{escape(paper.local_fulltext)}</code></li>" if paper.local_fulltext else "",
            f"<li>Local document: <code>{escape(paper.local_document)}</code></li>" if paper.local_document else "",
        ]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(paper.title)} · {escape(site_title)}</title>
  <link rel="stylesheet" href="../assets/style.css" />
</head>
<body>
  <header class="topbar"><a href="../index.html">← {escape(site_title)}</a></header>
  <main class="paper-detail">
    <section class="hero">
      <div class="eyebrow">{escape(paper.topic_slug)} / {escape(paper.source_label)}</div>
      <h1>{escape(paper.title)}</h1>
      <p class="meta">{escape(authors)} · {escape(paper.display_year)} · {escape(paper.display_venue)}</p>
      <div class="tags">{tags}</div>
    </section>

    <section>
      <h2>中文速览</h2>
      <p>{escape(paper.zh_brief or paper.summary or '待补充。')}</p>
    </section>

    <section>
      <h2>Summary</h2>
      <p>{escape(paper.summary or '待补充。')}</p>
    </section>

    <section>
      <h2>Abstract</h2>
      <p>{escape(paper.abstract or '待补充。')}</p>
    </section>

    <section>
      <h2>Links</h2>
      <ul>
        {link('Source / PDF', paper.source_url)}
        {link('Notion', paper.notion_url)}
        {local_assets}
      </ul>
    </section>
  </main>
</body>
</html>
"""


def _index_page(papers: list[ReaderPaper], site_title: str, slug_map: dict[str, str]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    topics = sorted({p.topic_slug for p in papers if p.topic_slug})
    sources = sorted({p.source_label for p in papers if p.source_label})
    topic_options = "".join(f'<option value="{escape(t)}">{escape(t)}</option>' for t in topics)
    source_options = "".join(f'<option value="{escape(s)}">{escape(s)}</option>' for s in sources)
    cards = "\n".join(_paper_card(p, f"papers/{slug_map[p.paper_id]}.html") for p in papers)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(site_title)}</title>
  <link rel="stylesheet" href="assets/style.css" />
</head>
<body>
  <aside class="sidebar">
    <h1>{escape(site_title)}</h1>
    <p>Notion × paper-search × Obsidian 深度论文阅读站</p>
    <input id="search" type="search" placeholder="Search title, summary, tags…" />
    <label>Topic <select id="topic"><option value="">All</option>{topic_options}</select></label>
    <label>Source <select id="source"><option value="">All</option>{source_options}</select></label>
    <a class="small-link" href="data/papers.json">Download metadata JSON</a>
  </aside>
  <main class="content">
    <section class="hero">
      <div class="eyebrow">Generated {escape(generated)}</div>
      <h2>Daily / Deep Paper Reader</h2>
      <p>一个跨平台可读的 PhD 论文工作台：Notion 管元数据，paper-search 做深度处理，Obsidian 保存本地知识资产，这里负责阅读体验。</p>
    </section>
    <section id="papers" class="paper-grid">
      {cards}
    </section>
  </main>
  <script src="assets/app.js"></script>
</body>
</html>
"""


STYLE_CSS = """
:root { color-scheme: dark; --bg:#080b12; --panel:#111827; --panel2:#172033; --text:#e5e7eb; --muted:#9ca3af; --brand:#8b5cf6; --line:#263244; }
* { box-sizing: border-box; }
body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top left, #1e1b4b 0, #080b12 36rem); color:var(--text); }
a { color:#c4b5fd; text-decoration:none; }
a:hover { text-decoration:underline; }
.sidebar { position:fixed; inset:0 auto 0 0; width:310px; padding:28px; background:rgba(17,24,39,.9); border-right:1px solid var(--line); backdrop-filter: blur(12px); overflow:auto; }
.sidebar h1 { margin:0 0 8px; font-size:26px; }
.sidebar p, .meta, .eyebrow { color:var(--muted); }
.sidebar input, .sidebar select { width:100%; margin:8px 0 16px; padding:10px 12px; border:1px solid var(--line); border-radius:12px; background:#0b1020; color:var(--text); }
.sidebar label { display:block; color:var(--muted); font-size:13px; }
.small-link { display:inline-block; margin-top:8px; font-size:13px; }
.content { margin-left:310px; padding:34px; }
.hero { background:linear-gradient(135deg, rgba(139,92,246,.22), rgba(14,165,233,.12)); border:1px solid var(--line); border-radius:24px; padding:28px; margin-bottom:24px; }
.hero h2, .hero h1 { margin:6px 0 10px; font-size:34px; }
.paper-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:18px; }
.paper-card { background:rgba(17,24,39,.78); border:1px solid var(--line); border-radius:20px; padding:18px; min-height:220px; box-shadow:0 16px 40px rgba(0,0,0,.18); }
.paper-title { display:block; font-weight:750; font-size:18px; line-height:1.35; margin-bottom:10px; color:#f5f3ff; }
.paper-card p { color:#cbd5e1; line-height:1.55; }
.tags { display:flex; flex-wrap:wrap; gap:7px; margin-top:12px; }
.tag { display:inline-flex; padding:4px 8px; border:1px solid rgba(196,181,253,.3); border-radius:999px; color:#ddd6fe; background:rgba(139,92,246,.12); font-size:12px; }
.topbar { padding:18px 28px; border-bottom:1px solid var(--line); background:rgba(17,24,39,.82); position:sticky; top:0; }
.paper-detail { max-width:920px; margin:0 auto; padding:30px 24px 80px; }
.paper-detail section { background:rgba(17,24,39,.72); border:1px solid var(--line); border-radius:20px; padding:22px; margin:18px 0; }
.paper-detail p { line-height:1.75; white-space:pre-wrap; }
code { color:#bae6fd; word-break:break-all; }
.hidden { display:none !important; }
@media (max-width: 800px) { .sidebar { position:static; width:auto; border-right:0; border-bottom:1px solid var(--line); } .content { margin-left:0; padding:18px; } .hero h1, .hero h2 { font-size:26px; } }
""".strip()


APP_JS = """
const search = document.getElementById('search');
const topic = document.getElementById('topic');
const source = document.getElementById('source');
const cards = Array.from(document.querySelectorAll('.paper-card'));
function applyFilters() {
  const q = (search?.value || '').toLowerCase();
  const t = topic?.value || '';
  const s = source?.value || '';
  cards.forEach(card => {
    const text = card.innerText.toLowerCase();
    const okQ = !q || text.includes(q);
    const okT = !t || card.dataset.topic === t;
    const okS = !s || card.dataset.source === s;
    card.classList.toggle('hidden', !(okQ && okT && okS));
  });
}
[search, topic, source].forEach(el => el && el.addEventListener('input', applyFilters));
""".strip()


def render_site(
    papers: list[ReaderPaper],
    output_dir: str | Path,
    *,
    site_title: str = "Sidney Deep Paper Reader",
) -> dict:
    """Render a static reader site and return a summary."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    papers_sorted = sorted(
        papers,
        key=lambda p: (p.updated_at or "", p.year or "", p.title.lower()),
        reverse=True,
    )
    used_slugs: set[str] = set()
    slug_map: dict[str, str] = {}
    for paper in papers_sorted:
        slug = paper_slug(paper)
        original = slug
        idx = 2
        while slug in used_slugs:
            slug = f"{original}-{idx}"
            idx += 1
        used_slugs.add(slug)
        slug_map[paper.paper_id] = slug

    _write(output / "assets" / "style.css", STYLE_CSS + "\n")
    _write(output / "assets" / "app.js", APP_JS + "\n")
    _write(output / "index.html", _index_page(papers_sorted, site_title, slug_map))
    _write(
        output / "data" / "papers.json",
        json.dumps([asdict(p) for p in papers_sorted], ensure_ascii=False, indent=2) + "\n",
    )

    for paper in papers_sorted:
        _write(output / "papers" / f"{slug_map[paper.paper_id]}.html", _detail_page(paper, site_title))

    breakdown: dict[str, int] = {}
    for paper in papers_sorted:
        key = f"{paper.topic_slug}/{paper.source_label}"
        breakdown[key] = breakdown.get(key, 0) + 1
    return {
        "output_dir": str(output),
        "papers": len(papers_sorted),
        "breakdown": breakdown,
        "site_title": site_title,
    }


def export_reader_site(
    *,
    topic_slug: str = "all",
    source: str = "all",
    output_dir: str | Path = "reader-site",
    limit: int | None = None,
    site_title: str = "Sidney Deep Paper Reader",
) -> dict:
    """Collect from Notion and render the static reader site."""

    papers = collect_reader_papers(topic_slug=topic_slug, source=source, limit=limit)
    summary = render_site(papers, output_dir, site_title=site_title)
    summary.update({"topic": topic_slug, "source": source})
    return summary
