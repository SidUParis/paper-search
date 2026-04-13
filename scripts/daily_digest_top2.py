#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DEFAULT_VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault"))).expanduser()
DEFAULT_OUT_MD = DEFAULT_VAULT / "dashboards" / "daily-digest.md"
DEFAULT_OUT_HTML = DEFAULT_VAULT / "dashboards" / "daily-digest.email.html"
CROSS_LINGUAL_NOTE = DEFAULT_VAULT / "methods" / "cross-lingual-evaluation.md"
REVIEW_MAP_NOTE = DEFAULT_VAULT / "reviews" / "multilingual-bias-benchmark-landscape-map.md"
TOP_K = 2


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return yaml.safe_load(text[4:end]) or {}, text[end + 5 :]
    return {}, text


SECTION_RE = re.compile(r"^#\s+(?P<title>[^\n]+)\n(?P<body>.*?)(?=^#\s+|\Z)", re.M | re.S)
SUBSECTION_RE = re.compile(r"^##\s+(?P<title>[^\n]+)\n(?P<body>.*?)(?=^##\s+|^#\s+|\Z)", re.M | re.S)
WIKILINK_RE = re.compile(r"\[\[papers/(?P<paper_id>[^\]]+)\]\]")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class Paper:
    def __init__(self, paper_id: str, frontmatter: dict[str, Any], body: str, note_path: Path):
        self.paper_id = paper_id
        self.fm = frontmatter
        self.body = body
        self.note_path = note_path
        self.sections = {m.group("title").strip(): m.group("body").strip() for m in SECTION_RE.finditer(body)}
        summary = self.sections.get("Summary", "")
        self.summary_sections = {m.group("title").strip(): m.group("body").strip() for m in SUBSECTION_RE.finditer(summary)}
        self.connections = [line.strip()[2:].strip() for line in self.sections.get("Connections", "").splitlines() if line.strip().startswith("-")]

    @property
    def title(self) -> str:
        return str(self.fm.get("title") or self.paper_id)

    @property
    def notion_url(self) -> str:
        return str(self.fm.get("notion_url") or "")

    @property
    def source_url(self) -> str:
        return str(self.fm.get("source_url") or "")

    @property
    def year(self) -> str:
        return str(self.fm.get("year") or "")

    @property
    def venue(self) -> str:
        return str(self.fm.get("venue") or "")

    @property
    def tags(self) -> list[str]:
        tags = self.fm.get("tags") or []
        return [str(x) for x in tags]

    @property
    def zh_summary(self) -> str:
        return normalize(self.sections.get("中文简述", ""))

    @property
    def method(self) -> str:
        return normalize(self.summary_sections.get("Method", ""))

    @property
    def results(self) -> str:
        return normalize(self.summary_sections.get("Results", ""))



def load_paper(note_path: Path) -> Paper:
    text = note_path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    return Paper(note_path.stem, fm, body, note_path)



def parse_review_map_ids(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    start = text.find("### High-value unified multilingual BBQ references")
    if start == -1:
        return []
    end = text.find("### High-value FrenchBBQ references", start)
    chunk = text[start:end if end != -1 else len(text)]
    ids = []
    for m in WIKILINK_RE.finditer(chunk):
        ids.append(m.group("paper_id"))
    return ids



def parse_cross_lingual_mentions(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {m.group("paper_id") for m in WIKILINK_RE.finditer(text)}



def score_paper(paper: Paper, cross_refs: set[str], review_rank: int) -> int:
    text = f"{paper.paper_id} {paper.title}".lower()
    score = 0
    if review_rank >= 0:
        score += max(0, 60 - review_rank)
    if paper.paper_id in cross_refs:
        score += 60
    if "bbq" in text:
        score += 50
    if "multilingual" in text or "cross-lingual" in paper.body.lower():
        score += 20
    if paper.notion_url:
        score += 15
    if "[[projects/frenchbbq]]" in paper.body:
        score += 20
    if "[[projects/multilingual-unified-bbq]]" in paper.body:
        score += 25
    if paper.zh_summary:
        score += 10
    return score



def bullet_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        raw = normalize(raw)
        if not raw:
            continue
        raw = raw.removeprefix("- ").strip()
        lines.append(raw)
    return lines



def paper_payload(paper: Paper) -> dict[str, Any]:
    pid = paper.paper_id
    if "bharatbbq" in pid:
        why = "这篇最适合今天先读，因为它直接回答你当前 multilingual unified BBQ 的两个核心设计问题：如何在多语言之间保留 shared core comparability，以及如何在文化适配后仍保持数据统计与评测协议一致。它还正好对应你在 cross-lingual evaluation 笔记里已经抽出来的原则——parallel core、language-balanced aggregation、不要过早把 bias 压成单一分数。"
        key_method = [
            "Benchmark：BharatBBQ，印度语境的 BBQ-style 多语言问答偏见基准。",
            "Language scope：8 种语言（English, Hindi, Marathi, Bengali, Tamil, Telugu, Odia, Assamese），每种语言 49,108 条，共 392,864 条。",
            "Bias type：以 social / cultural bias 为核心，覆盖 13 个社会类别，并加入 religion×gender、age×gender、region×gender 交叉维度。",
            "Method anchor：从 BBQ 出发做 cultural transformation + target-group adaptation + newly created categories，再用 IndicTransv2 翻译、回译相似度过滤和人工修订保证多语言对齐。",
            "Metrics：同时报告 Accuracy、Bias Score (BS)、Stereotypical Bias Score (SBS)。",
        ]
        takeaways = [
            "如果 unified BBQ 想保留强可比性，可以照抄它的“英语母版 + 多语翻译质控 + 统计一致”思路，先做一个 parallel shared-core。",
            "它证明“文化适配”与“结构对齐”并不矛盾：类别和刻板印象可以本地化，但模板规模、标签分布和评测协议仍然能保持一致。",
            "交叉类别设计值得直接借给 future multilingual unified BBQ，因为这比单轴 bias category 更接近真实社会语境。",
            "BS / SBS 分开报告非常适合你现在的 metric design 思路：不要只给一个最终 aggregate。",
        ]
        next_action = "今天值得读，而且建议精读：① dataset construction / category adaptation；② translation & verification pipeline；③ evaluation metrics（尤其 BS / SBS 的组织方式）。如果时间只够读一篇，先读它。"
    elif "basqbbq" in pid:
        why = "这篇今天也非常值得读，因为它和 FrenchBBQ 的问题形态更接近：不是单纯扩语言，而是在低资源、本土社会语境里把 BBQ 重新落地。它还能直接补上你当前 unified BBQ 设计里一个关键点——ambiguous vs. unambiguous bias 必须分开看，不能被单一 aggregate 吃掉。"
        key_method = [
            "Benchmark：BasqBBQ，首个面向 Basque 的社会偏见 QA benchmark。",
            "Language scope：Basque 为主，并与 English / translated settings 做 cross-language comparison。",
            "Bias type：social / cultural bias，覆盖 8 个类别：Age、Disability、Gender Identity、Nationality、Physical Appearance、Race/Ethnicity、Socio-Economic Status、Sexual Orientation。",
            "Method anchor：从原始 BBQ 进行模板筛选、神经翻译 + 人工后编辑、target group 本地化，并显式重写与 Basque 社会语境不匹配的内容。",
            "Metrics：Accuracy（ambiguous / unambiguous 分开）+ Biasa + Biasna，明确把模糊语境偏见和明示语境偏见拆开报告。",
        ]
        takeaways = [
            "对 FrenchBBQ 最有借鉴意义的是：它不是盲目保留原 BBQ 所有维度，而是先删掉不适合本地语境的 category，再做文化重写。",
            "它提醒你 future multilingual unified BBQ 不能只看平均 bias：同一模型在 ambiguous 与 unambiguous 条件下可能表现方向相反。",
            "Basque-adapted vs multilingual base model 的比较，对你未来讨论“language adaptation 是否会传递或改变 bias”非常有帮助。",
            "低资源语言 benchmark 的价值不只是补语言覆盖，而是暴露英文中心 benchmark 在 category choice 和 stereotype grounding 上的局限。",
        ]
        next_action = "今天应该读，建议精读：① template selection / target-group adaptation；② ambiguous vs unambiguous metric design；③ cross-language comparison 那一节。作为 FrenchBBQ 方法部分的对照文献尤其合适。"
    else:
        why = "它与当前 FrenchBBQ / multilingual unified BBQ 工作直接相关。"
        key_method = [paper.method or "Method: 见原文。"]
        takeaways = ["可作为 benchmark 设计与多语言偏见评测的参考。"]
        next_action = "今天可读，优先看方法与实验部分。"

    return {
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "why_today": why,
        "zh_summary": paper.zh_summary,
        "method_lines": key_method,
        "borrow_points": takeaways,
        "next_action": next_action,
        "notion_url": paper.notion_url,
        "source_url": paper.source_url,
    }



def markdown_from_payload(payloads: list[dict[str, Any]], generated_at: str) -> str:
    lines = [
        "# 📚 Daily Reading Digest（Top 2 完整版）",
        "",
        "> 面向：Sidney｜时区：Europe/Paris",
        f"> 生成时间：{generated_at}",
        "> 说明：今天只保留 2 篇，但每篇都写到足够支持研究判断与今天的阅读决策。",
        "",
        "## 今日总判断",
        "",
        "今天最该读的是两篇真正能直接反哺 FrenchBBQ / multilingual unified BBQ 设计的 benchmark paper：**BharatBBQ** 给你 parallel shared-core、翻译质控和多语言聚合的做法；**BasqBBQ** 则把低资源本土化 adaptation 与 ambiguous / unambiguous bias 拆分报告做得很清楚。两篇合起来，正好对应你当前 bias-fairness 主线里最急需补齐的方法空白。",
        "",
        "## 今日 Top 2（少而完整）",
        "",
    ]
    for idx, p in enumerate(payloads, 1):
        lines += [
            f"### {idx}. {p['title']}",
            f"- 年份 / venue：{p['year']} / {p['venue']}",
            f"- 为什么今天值得读：{p['why_today']}",
            "",
            "**中文摘要**",
            p["zh_summary"],
            "",
            "**关键方法 / benchmark / language scope / bias type**",
        ]
        lines.extend(f"- {x}" for x in p["method_lines"])
        lines += ["", "**最值得借鉴给当前研究的点**"]
        lines.extend(f"- {x}" for x in p["borrow_points"])
        lines += ["", f"**Next action**\n- {p['next_action']}", "", "**链接**"]
        lines.append(f"- Notion：{p['notion_url']}")
        lines.append(f"- 原文：{p['source_url']}")
        lines.append("")
    lines += [
        "## 建议阅读顺序",
        "",
        "1. 先读 BharatBBQ 的 dataset construction + metrics 章节，确定 shared-core 与 aggregate 的设计边界。",
        "2. 再读 BasqBBQ 的 adaptation + bias metrics 章节，把本土化 category 改写和 ambiguous / unambiguous 分开报告的方法补进 FrenchBBQ / unified BBQ 的方法笔记。",
        "",
    ]
    return "\n".join(lines)



def _inline_markup(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(https?://[^\s<]+)", lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text)
    return text


def html_from_markdown(md: str) -> str:
    lines = md.splitlines()
    out = [
        "<html><body style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;line-height:1.55;color:#222;max-width:860px;margin:0 auto;padding:24px;\">"
    ]
    in_list = False
    for raw in lines:
        line = raw.rstrip()
        if not line:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if line.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{_inline_markup(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_inline_markup(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{_inline_markup(line[2:])}</h1>")
        elif line.startswith("> "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p style=\"color:#555;margin:4px 0;\">{_inline_markup(line[2:])}</p>")
        elif line.startswith("- ") or re.match(r"^\d+\. ", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = re.sub(r"^(-|\d+\.)\s+", "", line)
            out.append(f"<li>{_inline_markup(item)}</li>")
        elif line.startswith("**") and line.endswith("**"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p><strong>{_inline_markup(line.strip('*'))}</strong></p>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{_inline_markup(line)}</p>")
    if in_list:
        out.append("</ul>")
    out.append("</body></html>")
    return "\n".join(out)



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    parser.add_argument("--out-html", default=str(DEFAULT_OUT_HTML))
    args = parser.parse_args()

    vault = Path(args.vault).expanduser()
    review_ids = parse_review_map_ids(vault / "reviews" / "multilingual-bias-benchmark-landscape-map.md")
    cross_refs = parse_cross_lingual_mentions(vault / "methods" / "cross-lingual-evaluation.md")

    candidates: list[tuple[int, Paper]] = []
    for idx, paper_id in enumerate(review_ids):
        note_path = vault / "papers" / f"{paper_id}.md"
        if not note_path.exists():
            continue
        paper = load_paper(note_path)
        score = score_paper(paper, cross_refs, idx)
        candidates.append((score, paper))

    candidates.sort(key=lambda item: (-item[0], -(int(item[1].year or 0)), item[1].title.lower()))
    selected = [paper for _, paper in candidates[:TOP_K]]
    payloads = [paper_payload(p) for p in selected]
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d (%a) %H:%M %Z")
    md = markdown_from_payload(payloads, generated_at)
    html_doc = html_from_markdown(md)

    out_md = Path(args.out_md).expanduser()
    out_html = Path(args.out_html).expanduser()
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md + "\n", encoding="utf-8")
    out_html.write_text(html_doc + "\n", encoding="utf-8")

    print(f"WROTE_MD={out_md}")
    print(f"WROTE_HTML={out_html}")
    print("SELECTED=" + " | ".join(p.title for p in selected))


if __name__ == "__main__":
    main()
