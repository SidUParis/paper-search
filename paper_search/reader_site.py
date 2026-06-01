"""Static reader-site export for the paper-search library.

This module is intentionally presentation-focused: Notion remains the
source-of-truth, Obsidian/local caches remain the durable asset layer, and the
reader site is a generated static view that can be published with GitHub Pages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import shutil
from typing import Any, cast
from urllib.parse import urlparse
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
    tldr: str = ""
    motivation: str = ""
    method: str = ""
    results: str = ""
    limitations: str = ""
    relevance: str = ""
    notebooklm_audio: str = ""
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
    tldr = _first_existing_text_prop(props, ("TLDR", "TL;DR", "Tldr", "One-line TLDR", "一句话总结"))
    motivation = _first_existing_text_prop(props, ("Motivation", "Research Motivation", "研究动机"))
    method = _first_existing_text_prop(props, ("Method", "Methods", "Approach", "方法"))
    results = _first_existing_text_prop(props, ("Results", "Findings", "Key Findings", "实验结果", "结果"))
    limitations = _first_existing_text_prop(props, ("Limitations", "Weaknesses", "局限"))
    relevance = _first_existing_text_prop(props, ("Relevance", "Why Relevant", "PhD Relevance", "Related to My Work", "与我相关"))
    notebooklm_audio = _first_existing_text_prop(props, ("NotebookLM Audio", "NotebookLM", "Deep Dive Audio", "Audio"))
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
        tldr=tldr,
        motivation=motivation,
        method=method,
        results=results,
        limitations=limitations,
        relevance=relevance,
        notebooklm_audio=notebooklm_audio,
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


def _safe_external_href(url: str) -> str:
    """Allow only browser-safe external schemes in generated href attributes."""

    if not url or any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in url):
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "mailto", "doi"}:
        return ""
    return url


def _strip_sensitive_url(url: str) -> str:
    """Return a safe public URL or an empty string."""

    if not url:
        return ""
    clean = url.split("?", 1)[0].split("#", 1)[0]
    clean = _sanitize_public_text(clean)
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if parsed.netloc.lower().endswith(("notion.so", "notion.site")):
        return ""
    return clean


def _sanitize_public_text(text: str) -> str:
    """Best-effort public-export scrubber for secrets and local paths."""

    if not text:
        return ""
    scrubbed = text
    scrubbed = re.sub(r"https?://[^\s)\]}>\"']*notion\.(?:so|site)(?:/[^\s)\]}>\"']*)?", "[PRIVATE_URL_REDACTED]", scrubbed, flags=re.I)
    scrubbed = re.sub(r"file://[^\s)\]}>\"']+", "[LOCAL_PATH_REDACTED]", scrubbed, flags=re.I)
    scrubbed = re.sub(
        r"(?i)[\"']?[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|AUTHORIZATION)[A-Z0-9_]*[\"']?\s*[:=]\s*[\"'][^\"']+[\"']",
        "[SECRET_REDACTED]",
        scrubbed,
    )
    scrubbed = re.sub(r"(?i)\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|AUTHORIZATION)[A-Z0-9_]*\s*[:=]\s*\S+", "[SECRET_REDACTED]", scrubbed)
    scrubbed = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "[SECRET_REDACTED]", scrubbed)
    scrubbed = re.sub(r"(?i)\bsk-[A-Za-z0-9._-]{8,}", "[SECRET_REDACTED]", scrubbed)
    scrubbed = re.sub(r"/(?:home|Users|vault)(?:/[^\s)\]}>\"']*)?", "[LOCAL_PATH_REDACTED]", scrubbed)
    scrubbed = re.sub(r"(?<![A-Za-z])[A-Za-z]:[/\\\\]+[^\s)\]}>\"']+", "[LOCAL_PATH_REDACTED]", scrubbed)
    scrubbed = re.sub(r"(?i)Obsidian\s+Vault[^\s)\]}>\"']*", "[LOCAL_PATH_REDACTED]", scrubbed)
    return scrubbed


def _sanitize_public_list(values: list[str]) -> list[str]:
    sanitized = [_sanitize_public_text(value).strip() for value in values]
    return [value for value in sanitized if value and value not in {"[LOCAL_PATH_REDACTED]", "[PRIVATE_URL_REDACTED]", "[SECRET_REDACTED]"}]


def public_safe_paper(paper: ReaderPaper) -> ReaderPaper:
    """Return a GitHub-Pages-safe view of a paper with private fields removed."""

    sanitized = {
        field_name: _sanitize_public_text(value)
        for field_name, value in asdict(paper).items()
        if isinstance(value, str)
        and field_name
        not in {"source_url", "notion_url", "obsidian_note", "local_fulltext", "local_document", "notebooklm_audio"}
    }
    return replace(
        paper,
        **sanitized,
        source_url=_strip_sensitive_url(_sanitize_public_text(paper.source_url)),
        notion_url="",
        obsidian_note="",
        local_fulltext="",
        local_document="",
        notebooklm_audio="",
        authors=_sanitize_public_list(paper.authors),
        tags=_sanitize_public_list(paper.tags),
    )


def prepare_papers_for_profile(papers: list[ReaderPaper], profile: str) -> list[ReaderPaper]:
    """Normalize papers for either private local reading or public GitHub Pages."""

    if profile not in {"private", "public"}:
        raise ValueError("profile must be 'private' or 'public'")
    if profile == "public":
        return [public_safe_paper(p) for p in papers]
    return papers


def _section(title: str, body: str) -> str:
    if not body:
        return ""
    return f"""
    <section>
      <h2>{escape(title)}</h2>
      <p>{escape(body)}</p>
    </section>
    """


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
        safe_url = _safe_external_href(url)
        if not safe_url:
            return ""
        safe = escape(safe_url, quote=True)
        return f'<li><a href="{safe}" target="_blank" rel="noreferrer">{escape(label)}</a></li>'

    local_assets = "".join(
        item
        for item in [
            f"<li>Obsidian note: <code>{escape(paper.obsidian_note)}</code></li>" if paper.obsidian_note else "",
            f"<li>Local fulltext: <code>{escape(paper.local_fulltext)}</code></li>" if paper.local_fulltext else "",
            f"<li>Local document: <code>{escape(paper.local_document)}</code></li>" if paper.local_document else "",
            f"<li>NotebookLM audio: <code>{escape(paper.notebooklm_audio)}</code></li>" if paper.notebooklm_audio else "",
        ]
    )
    deep_sections = "".join(
        [
            _section("TL;DR", paper.tldr),
            _section("Motivation / 研究动机", paper.motivation),
            _section("Method / 方法", paper.method),
            _section("Results / 结果", paper.results),
            _section("Limitations / 局限", paper.limitations),
            _section("Why relevant to Sidney PhD / 与我的博士相关性", paper.relevance),
        ]
    )
    preset_questions = [
        ("中文讲解", "请用中文解释这篇论文的核心问题、方法和贡献，适合我快速读懂。"),
        ("方法拆解", "请拆解这篇论文的方法：输入、模型/算法、实验设置、关键假设分别是什么？"),
        ("实验结果", "请总结这篇论文的主要实验结果、指标、对比方法，以及最重要的表格/图。"),
        ("局限性", "请批判性分析这篇论文的局限性、可能的偏差、威胁有效性的因素。"),
        ("和我的 PhD 关系", "请说明这篇论文和我的 LLM bias / BBQ / MultilingualBBQ / fairness evaluation 博士课题有什么关系，可以怎么引用或扩展？"),
        ("Related Work 可引用点", "请提炼这篇论文作为 related work 时可引用的 3-5 个点，并给出中文说明。"),
    ]
    preset_buttons = "".join(
        f'<button type="button" class="preset-chip" data-prompt="{escape(prompt, quote=True)}">{escape(label)}</button>'
        for label, prompt in preset_questions
    )
    paper_key = escape(paper.paper_id, quote=True)
    ask_panel = f"""
    <section class="ai-terminal paper-ask-panel" aria-label="Ask While Reading" data-paper-key="{paper_key}">
      <div class="terminal-header">
        <div>
          <div class="eyebrow">Read in Context · 当前论文</div>
          <h2>Ask While Reading</h2>
          <p class="terminal-subtitle">所有回答都会自动带上这篇论文的摘要、中文速览、fulltext excerpt 和 related context。</p>
        </div>
        <span id="chat-status" class="terminal-status">ready</span>
      </div>
      <div class="preset-row">{preset_buttons}</div>
      <div id="chat-log" class="chat-log">
        <div class="chat-msg assistant">我已经准备好阅读《{escape(paper.title)}》。可以点上面的预设问题，或直接问你自己的问题。</div>
      </div>
      <form id="global-chat-form" class="composer-form" data-paper-key="{paper_key}">
        <textarea id="chat-question" placeholder="Ask about this paper… / 问这篇论文" rows="3"></textarea>
        <button type="submit">Ask this paper</button>
        <div class="composer-meta">Read in Context: metadata + fulltext excerpt + related papers；模型配置在首页 Model Settings。</div>
      </form>
    </section>
    """
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
      <p>{escape(paper.zh_brief or paper.tldr or paper.summary or '待补充。')}</p>
    </section>

    {ask_panel}

    {deep_sections}

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
  <script src="../assets/app.js?v=ai-reader-3"></script>
</body>
</html>
"""


def _index_page(papers: list[ReaderPaper], site_title: str, slug_map: dict[str, str], profile: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    topics = sorted({p.topic_slug for p in papers if p.topic_slug})
    sources = sorted({p.source_label for p in papers if p.source_label})
    topic_options = "".join(f'<option value="{escape(t)}">{escape(t)}</option>' for t in topics)
    source_options = "".join(f'<option value="{escape(s)}">{escape(s)}</option>' for s in sources)
    cards = "\n".join(_paper_card(p, f"papers/{slug_map[p.paper_id]}.html") for p in papers)
    queue_cards = "\n".join(
        f'<a class="queue-item" href="papers/{escape(slug_map[p.paper_id], quote=True)}.html">'
        f'<span class="queue-title">{escape(p.title[:88])}{"…" if len(p.title) > 88 else ""}</span>'
        f'<span class="queue-meta">{escape(p.display_year)} · {escape(p.display_venue)} · {escape(p.status or "paper")}</span>'
        f'</a>'
        for p in papers[:6]
    )
    deep_count = sum(bool(p.tldr or p.motivation or p.method or p.results or p.limitations or p.relevance) for p in papers)
    profile_note = "Public GitHub Pages-safe export: private Notion, Obsidian, local path, and token-like fields are removed." if profile == "public" else "Private local export: includes Notion/Obsidian/local asset paths for your own workflow."
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(site_title)}</title>
  <link rel="stylesheet" href="assets/style.css" />
</head>
<body class="reader-home">
  <header class="app-header">
    <div class="brand-block">
      <div class="brand-mark">AI</div>
      <div>
        <div class="eyebrow">Generated {escape(generated)} · {escape(profile.upper())} · Cloudflare Access</div>
        <h1>{escape(site_title)}</h1>
        <p>一个私有 AI paper reading workbench：搜索、精读、问答、模型切换和后续 sync 都在网页里完成。</p>
      </div>
    </div>
    <div class="header-actions">
      <span class="status-pill">Protected</span>
      <a class="metadata-link" href="data/papers.json">Metadata JSON</a>
    </div>
  </header>

  <main class="app-main">
    <nav class="workspace-tabs" aria-label="Reader workspaces">
      <button type="button" class="workspace-tab active" data-view-target="ai-view">AI 阅读 / Chat</button>
      <button type="button" class="workspace-tab" data-view-target="library-view">Paper Cards / Library</button>
      <button type="button" class="workspace-tab" data-view-target="settings-view">Model Settings</button>
    </nav>

    <section class="overview-grid" aria-label="Reader capabilities">
      <div class="overview-card accent"><span>01</span><strong>Ask While Reading</strong><p>每篇论文都有中文预设问题。</p></div>
      <div class="overview-card"><span>02</span><strong>Read in Context</strong><p>metadata + fulltext excerpt + related papers。</p></div>
      <div class="overview-card"><span>03</span><strong>Model Router</strong><p>DeepSeek / OpenRouter / OpenAI-compatible。</p></div>
      <div class="overview-card"><span>04</span><strong>Paper Library</strong><p>{len(papers)} papers ready for AI reading。</p></div>
    </section>

    <section id="ai-view" class="workspace-view active">
      <div class="reader-dashboard">
        <section class="ai-terminal hero-terminal" aria-label="AI Reading Terminal">
          <div class="terminal-header">
            <div>
              <div class="eyebrow">Read in Context · Whole library</div>
              <h2>AI Reading Terminal</h2>
              <p class="terminal-subtitle">像 ChatGPT / Claude 一样直接问你的论文库。后端会先检索相关论文，再用服务端模型 grounded 回答。</p>
            </div>
            <span id="chat-status" class="terminal-status">ready</span>
          </div>
          <div class="preset-row">
            <button type="button" class="preset-chip" data-prompt="哪些论文和 BBQ / FrenchBBQ / MultilingualBBQ 最相关？">BBQ 相关论文</button>
            <button type="button" class="preset-chip" data-prompt="请按和我的 LLM bias 博士课题相关性排序推荐 5 篇论文，并解释原因。">PhD relevance ranking</button>
            <button type="button" class="preset-chip" data-prompt="今天最值得精读的论文是哪几篇？请给中文理由。">今日精读建议</button>
          </div>
          <div id="chat-log" class="chat-log">
            <div class="chat-msg assistant">你好，我是你的私有论文阅读助手。可以问整个 library，也可以进入单篇论文后问贡献、方法、局限和与你 PhD 的关系。</div>
          </div>
          <form id="global-chat-form" class="composer-form">
            <textarea id="chat-question" placeholder="Ask across your paper library… / 用中文问你的论文库" rows="3"></textarea>
            <button type="submit">Ask AI</button>
            <div class="composer-meta">当前模型：<span data-model-label>DeepSeek · deepseek-v4-flash</span> · API key 只在服务端保存</div>
          </form>
        </section>

        <aside class="reader-side-panel">
          <section class="mini-card snapshot-card">
            <h3>Library Snapshot</h3>
            <div class="stats vertical"><span>{len(papers)} Papers</span><span>{len(topics)} Topics</span><span>{len(sources)} Sources</span><span>{deep_count} Deep Sections</span></div>
          </section>
          <section class="mini-card queue-card">
            <div class="card-heading-row"><h3>Reading Queue</h3><span>latest</span></div>
            <div class="queue-list">{queue_cards}</div>
          </section>
          <section class="mini-card workflow-card">
            <h3>Workflow</h3>
            <p class="profile-note">{escape(profile_note)}</p>
          </section>
        </aside>
      </div>
    </section>

    <section id="library-view" class="workspace-view">
      <div class="library-toolbar">
        <div>
          <div class="eyebrow">Paper Library</div>
          <h2>Cards are separated from AI chat</h2>
        </div>
        <div class="library-controls">
          <input id="search" type="search" placeholder="Search title, summary, tags…" />
          <label>Topic <select id="topic"><option value="">All</option>{topic_options}</select></label>
          <label>Source <select id="source"><option value="">All</option>{source_options}</select></label>
        </div>
      </div>
      <section id="papers" class="paper-grid">
        {cards}
      </section>
    </section>

    <section id="settings-view" class="workspace-view">
      <section class="settings-panel">
        <div class="eyebrow">Server-side model configuration</div>
        <h2>Model Settings</h2>
        <p>这里先放轻量选择器；API key 不进入浏览器。完整 provider 管理会在 Admin dashboard 阶段接上。</p>
        <div class="settings-grid">
          <label>Provider<select id="chat-provider" aria-label="LLM provider"><option value="deepseek">DeepSeek</option><option value="openrouter">OpenRouter</option><option value="openai">OpenAI</option></select></label>
          <label>Model<input id="chat-model" aria-label="Model name" value="deepseek-v4-flash" /></label>
        </div>
      </section>
    </section>
  </main>
  <script src="assets/app.js?v=ai-reader-3"></script>
</body>
</html>
"""

STYLE_CSS = """
:root { color-scheme: dark; --bg:#070a12; --panel:#101827; --panel2:#162033; --text:#e5e7eb; --muted:#9ca3af; --brand:#8b5cf6; --brand2:#0ea5e9; --line:#263244; --soft:rgba(148,163,184,.13); }
* { box-sizing: border-box; }
body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: radial-gradient(circle at top left, #1e1b4b 0, #070a12 38rem); color:var(--text); }
a { color:#c4b5fd; text-decoration:none; }
a:hover { text-decoration:underline; }
.reader-home { min-height:100vh; }
.app-header { display:flex; justify-content:space-between; gap:24px; align-items:flex-start; padding:26px 36px 18px; border-bottom:1px solid var(--line); background:rgba(7,10,18,.78); backdrop-filter:blur(18px); position:sticky; top:0; z-index:20; }
.app-header h1 { margin:5px 0 8px; font-size:30px; letter-spacing:-.03em; }
.app-header p { margin:0; color:#cbd5e1; max-width:900px; }
.metadata-link { white-space:nowrap; border:1px solid rgba(196,181,253,.28); border-radius:999px; padding:9px 12px; background:rgba(139,92,246,.11); }
.app-main { max-width:1380px; margin:0 auto; padding:22px 30px 60px; }
.workspace-tabs { display:flex; gap:10px; margin:0 0 18px; padding:8px; border:1px solid var(--line); background:rgba(15,23,42,.72); border-radius:18px; width:max-content; max-width:100%; overflow:auto; }
.workspace-tab { border:1px solid transparent; border-radius:13px; padding:10px 14px; background:transparent; color:#cbd5e1; font-weight:700; cursor:pointer; white-space:nowrap; }
.workspace-tab.active { background:linear-gradient(135deg, rgba(139,92,246,.35), rgba(14,165,233,.22)); border-color:rgba(196,181,253,.34); color:white; }
.workspace-view { display:none; }
.workspace-view.active { display:block; }
.reader-dashboard { display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:20px; align-items:start; }
.ai-terminal { background:linear-gradient(180deg, rgba(15,23,42,.96), rgba(17,24,39,.88)); border:1px solid rgba(139,92,246,.38); border-radius:28px; padding:24px; box-shadow:0 24px 70px rgba(0,0,0,.28); }
.hero-terminal { min-height:670px; display:flex; flex-direction:column; }
.terminal-header { display:flex; justify-content:space-between; gap:18px; align-items:flex-start; margin-bottom:16px; }
.terminal-header h2 { margin:4px 0 0; font-size:34px; letter-spacing:-.04em; }
.terminal-subtitle { margin:8px 0 0; color:#cbd5e1; max-width:820px; line-height:1.65; }
.terminal-status { border:1px solid rgba(34,211,238,.35); color:#a5f3fc; background:rgba(8,145,178,.14); border-radius:999px; padding:6px 11px; font-size:12px; }
.eyebrow { color:#93c5fd; text-transform:uppercase; letter-spacing:.1em; font-size:12px; font-weight:800; }
.preset-row { display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 14px; }
.preset-chip { border:1px solid rgba(196,181,253,.36); border-radius:999px; color:#ddd6fe; background:rgba(139,92,246,.14); padding:8px 12px; font-size:13px; cursor:pointer; }
.preset-chip:hover { background:rgba(139,92,246,.25); border-color:rgba(196,181,253,.58); }
.chat-log { flex:1; display:flex; flex-direction:column; gap:12px; min-height:340px; max-height:560px; overflow:auto; padding:16px; border:1px solid var(--line); border-radius:22px; background:rgba(3,7,18,.72); }
.chat-msg { max-width:84%; padding:12px 14px; border-radius:18px; white-space:pre-wrap; line-height:1.68; }
.chat-msg.user { align-self:flex-end; background:linear-gradient(135deg, rgba(139,92,246,.38), rgba(14,165,233,.24)); color:#f8fafc; }
.chat-msg.assistant { align-self:flex-start; background:rgba(30,41,59,.92); color:#dbeafe; }
.chat-msg.error { align-self:flex-start; background:rgba(127,29,29,.68); color:#fecaca; }
.composer-form { margin-top:14px; display:grid; grid-template-columns:1fr auto; gap:10px; align-items:end; }
.composer-form textarea { min-height:90px; resize:vertical; grid-column:1 / 2; }
.composer-form textarea, .settings-grid input, .settings-grid select, .library-controls input, .library-controls select { width:100%; padding:12px 13px; border:1px solid var(--line); border-radius:14px; background:#0b1020; color:var(--text); outline:none; font:inherit; }
.composer-form textarea:focus, .settings-grid input:focus, .settings-grid select:focus, .library-controls input:focus, .library-controls select:focus { border-color:rgba(139,92,246,.75); box-shadow:0 0 0 3px rgba(139,92,246,.18); }
.composer-form button { min-height:48px; border:0; border-radius:14px; padding:12px 22px; background:linear-gradient(135deg,#8b5cf6,#0ea5e9); color:white; font-weight:800; cursor:pointer; }
.composer-form button:disabled { opacity:.62; cursor:wait; }
.composer-meta { grid-column:1 / -1; color:#94a3b8; font-size:12px; }
.reader-side-panel { display:flex; flex-direction:column; gap:14px; }
.mini-card, .settings-panel, .library-toolbar { border:1px solid var(--line); border-radius:24px; padding:20px; background:rgba(15,23,42,.76); }
.mini-card h3, .settings-panel h2, .library-toolbar h2 { margin:6px 0 12px; }
.stats { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
.stats.vertical { flex-direction:column; }
.stats span { border:1px solid rgba(196,181,253,.28); background:rgba(15,23,42,.55); padding:9px 11px; border-radius:13px; color:#ddd6fe; font-size:13px; }
.profile-note, .meta { color:#cbd5e1; line-height:1.65; }
.library-toolbar { display:flex; justify-content:space-between; align-items:end; gap:18px; margin-bottom:18px; }
.library-controls { display:grid; grid-template-columns:minmax(220px,320px) minmax(140px,180px) minmax(140px,180px); gap:10px; align-items:end; }
.library-controls label, .settings-grid label { color:#94a3b8; font-size:12px; display:flex; flex-direction:column; gap:5px; }
.paper-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:18px; }
.paper-card { background:rgba(17,24,39,.78); border:1px solid var(--line); border-radius:20px; padding:18px; min-height:220px; box-shadow:0 16px 40px rgba(0,0,0,.18); }
.paper-title { display:block; font-weight:750; font-size:18px; line-height:1.35; margin-bottom:10px; color:#f5f3ff; }
.paper-card p { color:#cbd5e1; line-height:1.55; }
.tags { display:flex; flex-wrap:wrap; gap:7px; margin-top:12px; }
.tag { display:inline-flex; padding:4px 8px; border:1px solid rgba(196,181,253,.3); border-radius:999px; color:#ddd6fe; background:rgba(139,92,246,.12); font-size:12px; }
.settings-grid { display:grid; grid-template-columns:repeat(2,minmax(220px,1fr)); gap:12px; margin-top:14px; }
.topbar { padding:18px 28px; border-bottom:1px solid var(--line); background:rgba(17,24,39,.82); position:sticky; top:0; }
.paper-detail { max-width:980px; margin:0 auto; padding:30px 24px 80px; }
.hero { background:linear-gradient(135deg, rgba(139,92,246,.22), rgba(14,165,233,.12)); border:1px solid var(--line); border-radius:24px; padding:28px; margin-bottom:24px; }
.hero h2, .hero h1 { margin:6px 0 10px; font-size:34px; }
.paper-detail section { background:rgba(17,24,39,.72); border:1px solid var(--line); border-radius:20px; padding:22px; margin:18px 0; }
.paper-detail p { line-height:1.75; white-space:pre-wrap; }
.paper-ask-panel .composer-form { grid-template-columns:1fr auto; }
code { color:#bae6fd; word-break:break-all; }
.hidden { display:none !important; }
@media (max-width: 980px) { .app-header { position:static; padding:22px; flex-direction:column; } .app-main { padding:16px; } .reader-dashboard { grid-template-columns:1fr; } .library-toolbar { flex-direction:column; align-items:stretch; } .library-controls { grid-template-columns:1fr; } .settings-grid { grid-template-columns:1fr; } .composer-form { grid-template-columns:1fr; } .composer-form textarea { grid-column:auto; } .terminal-header h2 { font-size:28px; } }

body::before { content:""; position:fixed; inset:0; pointer-events:none; background: radial-gradient(circle at 18% 12%, rgba(113,112,255,.25), transparent 28rem), radial-gradient(circle at 82% 8%, rgba(14,165,233,.18), transparent 24rem), linear-gradient(180deg, rgba(255,255,255,.025), transparent 18rem); z-index:-1; }
.app-header { margin:18px auto 0; width:calc(100% - 48px); max-width:1380px; border:1px solid rgba(255,255,255,.08); border-radius:24px; box-shadow:0 30px 80px rgba(0,0,0,.28); }
.brand-block { display:flex; gap:16px; align-items:center; }
.brand-mark { flex:0 0 54px; height:54px; display:grid; place-items:center; border-radius:18px; background:linear-gradient(135deg,#5e6ad2,#0ea5e9); color:white; font-weight:850; letter-spacing:-.05em; box-shadow:0 14px 40px rgba(94,106,210,.35); }
.header-actions { display:flex; align-items:center; gap:10px; }
.status-pill { color:#bbf7d0; background:rgba(16,185,129,.12); border:1px solid rgba(16,185,129,.28); border-radius:999px; padding:9px 12px; font-size:13px; font-weight:650; }
.workspace-tabs { margin-inline:auto; }
.overview-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:0 0 20px; }
.overview-card { min-height:116px; border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:16px; background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.025)); box-shadow:inset 0 1px 0 rgba(255,255,255,.06); }
.overview-card.accent { background:linear-gradient(135deg,rgba(94,106,210,.48),rgba(14,165,233,.17)); border-color:rgba(130,143,255,.42); }
.overview-card span { display:inline-flex; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; color:#93c5fd; font-size:12px; margin-bottom:18px; }
.overview-card strong { display:block; color:#f7f8f8; font-size:16px; margin-bottom:6px; letter-spacing:-.02em; }
.overview-card p { margin:0; color:#9ca3af; line-height:1.45; font-size:13px; }
.reader-dashboard { grid-template-columns:minmax(0,1fr) 360px; }
.ai-terminal { position:relative; overflow:hidden; }
.ai-terminal::before { content:""; position:absolute; inset:0 0 auto 0; height:1px; background:linear-gradient(90deg,transparent,rgba(130,143,255,.9),transparent); }
.hero-terminal { min-height:620px; }
.chat-log { background:radial-gradient(circle at 30% 0%, rgba(94,106,210,.14), transparent 24rem), rgba(3,7,18,.78); }
.chat-log::after { content:""; flex:1; min-height:70px; }
.reader-side-panel .mini-card { box-shadow:inset 0 1px 0 rgba(255,255,255,.05), 0 18px 50px rgba(0,0,0,.22); }
.snapshot-card .stats span { display:flex; justify-content:space-between; }
.card-heading-row { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; }
.card-heading-row h3 { margin:0; }
.card-heading-row span { color:#93c5fd; border:1px solid rgba(147,197,253,.28); background:rgba(147,197,253,.1); border-radius:999px; padding:4px 8px; font-size:11px; }
.queue-list { display:flex; flex-direction:column; gap:8px; }
.queue-item { display:block; padding:11px 12px; border:1px solid rgba(255,255,255,.07); border-radius:14px; background:rgba(255,255,255,.025); }
.queue-item:hover { text-decoration:none; background:rgba(113,112,255,.12); border-color:rgba(113,112,255,.35); }
.queue-title { display:block; color:#f7f8f8; font-size:13px; line-height:1.35; }
.queue-meta { display:block; margin-top:5px; color:#8a8f98; font-size:12px; }
.composer-form { padding:10px; border:1px solid rgba(255,255,255,.08); border-radius:22px; background:rgba(255,255,255,.03); }
.composer-form textarea { border:0; background:transparent; min-height:80px; }
.composer-form textarea:focus { box-shadow:none; border:0; }
.composer-form button { align-self:stretch; min-width:96px; }
.library-toolbar, .settings-panel { box-shadow:inset 0 1px 0 rgba(255,255,255,.05), 0 18px 50px rgba(0,0,0,.2); }
.paper-card { transition:transform .16s ease, border-color .16s ease, background .16s ease; }
.paper-card:hover { transform:translateY(-2px); border-color:rgba(113,112,255,.38); background:rgba(255,255,255,.045); }
@media (max-width: 1180px) { .overview-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .reader-dashboard { grid-template-columns:1fr; } }
@media (max-width: 980px) { .app-header { width:calc(100% - 24px); margin-top:12px; } .brand-block { align-items:flex-start; } .header-actions { width:100%; justify-content:space-between; } .overview-grid { grid-template-columns:1fr; } }

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

document.querySelectorAll('.workspace-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.viewTarget;
    document.querySelectorAll('.workspace-tab').forEach(item => item.classList.toggle('active', item === tab));
    document.querySelectorAll('.workspace-view').forEach(view => view.classList.toggle('active', view.id === target));
  });
});

const chatForm = document.getElementById('global-chat-form');
const chatLog = document.getElementById('chat-log');
const chatStatus = document.getElementById('chat-status');
const chatQuestion = document.getElementById('chat-question');
const providerEl = document.getElementById('chat-provider');
const modelEl = document.getElementById('chat-model');
const modelLabel = document.querySelector('[data-model-label]');
function syncModelLabel() {
  if (!modelLabel) return;
  const providerText = providerEl?.selectedOptions?.[0]?.textContent || providerEl?.value || 'provider';
  const modelText = modelEl?.value || 'default model';
  modelLabel.textContent = `${providerText} · ${modelText}`;
}
[providerEl, modelEl].forEach(el => el && el.addEventListener('input', syncModelLabel));
syncModelLabel();

function addChatMessage(role, text) {
  if (!chatLog) return;
  const msg = document.createElement('div');
  msg.className = `chat-msg ${role}`;
  msg.textContent = text;
  chatLog.appendChild(msg);
  chatLog.scrollTop = chatLog.scrollHeight;
}
document.querySelectorAll('.preset-chip').forEach(button => {
  button.addEventListener('click', () => {
    if (!chatQuestion) return;
    chatQuestion.value = button.dataset.prompt || button.textContent || '';
    chatQuestion.focus();
  });
});
chatForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const questionEl = document.getElementById('chat-question');
  const submitButton = chatForm.querySelector('button[type="submit"]');
  const question = (questionEl?.value || '').trim();
  const paperKey = chatForm.dataset.paperKey || document.querySelector('[data-paper-key]')?.dataset.paperKey || '';
  if (!question) return;
  addChatMessage('user', question);
  if (questionEl) questionEl.value = '';
  if (chatStatus) chatStatus.textContent = 'thinking…';
  if (submitButton) { submitButton.disabled = true; submitButton.textContent = 'Thinking…'; }
  try {
    const body = {
      question,
      provider_id: providerEl?.value || 'deepseek',
      model: modelEl?.value || '',
      mode: paperKey ? 'balanced' : 'library',
      max_tokens: paperKey ? 2400 : 4000
    };
    if (paperKey) body.paper_key = paperKey;
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || data.error || 'chat failed');
    addChatMessage('assistant', data.answer || 'No answer returned.');
  } catch (error) {
    addChatMessage('error', `Error: ${error.message || error}`);
  } finally {
    if (chatStatus) chatStatus.textContent = 'ready';
    if (submitButton) { submitButton.disabled = false; submitButton.textContent = paperKey ? 'Ask this paper' : 'Ask AI'; }
  }
});
""".strip()


def _catalog_payload() -> dict[str, Any]:
    topics = load_topics()
    safe_topics: list[dict[str, Any]] = []
    source_set: set[str] = set()
    for slug, cfg in topics.items():
        sources: list[str] = []
        if cfg.get("acl_data_source_id"):
            sources.append("ACL")
        if cfg.get("arxiv_data_source_id"):
            sources.append("arxiv")
        if cfg.get("scholar_data_source_id"):
            sources.append("Scholar")
        sources.extend(str(venue) for venue in cfg.get("acl_venues", []) if venue)
        sources.extend(str(venue) for venue in cfg.get("scholar_venues", []) if venue)
        source_set.update(sources)
        safe_topics.append(
            {
                "slug": slug,
                "name": str(cfg.get("name") or slug),
                "keywords": list(cfg.get("keywords") or [])[:20],
                "sources": sorted(set(sources), key=str.lower),
            }
        )
    return {"topics": safe_topics, "sources": sorted(source_set, key=str.lower)}


def render_site(
    papers: list[ReaderPaper],
    output_dir: str | Path,
    *,
    site_title: str = "Sidney Deep Paper Reader",
    profile: str = "private",
) -> dict:
    """Render a static reader site and return a summary."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for stale in (output / "index.html", output / "data", output / "assets", output / "papers"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
    for stale_html in output.glob("*.html"):
        stale_html.unlink()
    papers_for_profile = prepare_papers_for_profile(papers, profile)
    papers_sorted = sorted(
        papers_for_profile,
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

    web_dir = Path(__file__).resolve().parent / "reader_web"
    if web_dir.exists():
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        for template_path in web_dir.glob("*.html"):
            rendered = (
                template_path.read_text(encoding="utf-8")
                .replace("__SITE_TITLE__", site_title)
                .replace("__GENERATED__", generated)
                .replace("__PROFILE__", profile.upper())
            )
            _write(output / template_path.name, rendered)
        shutil.copytree(web_dir / "assets", output / "assets", dirs_exist_ok=True)
    else:  # fallback for source distributions missing reader_web assets
        _write(output / "assets" / "style.css", STYLE_CSS + "\n")
        _write(output / "assets" / "app.js", APP_JS + "\n")
        _write(output / "index.html", _index_page(papers_sorted, site_title, slug_map, profile))
    _write(
        output / "data" / "papers.json",
        json.dumps([asdict(p) for p in papers_sorted], ensure_ascii=False, indent=2) + "\n",
    )
    _write(
        output / "data" / "catalog.json",
        json.dumps(_catalog_payload(), ensure_ascii=False, indent=2) + "\n",
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
        "profile": profile,
    }


def export_reader_site(
    *,
    topic_slug: str = "all",
    source: str = "all",
    output_dir: str | Path = "reader-site",
    limit: int | None = None,
    site_title: str = "Sidney Deep Paper Reader",
    profile: str = "private",
) -> dict:
    """Collect from Notion and render the static reader site."""

    papers = collect_reader_papers(topic_slug=topic_slug, source=source, limit=limit)
    summary = render_site(papers, output_dir, site_title=site_title, profile=profile)
    summary.update({"topic": topic_slug, "source": source})
    return summary
