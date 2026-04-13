from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner


def test_load_review_project_parses_yaml_and_topic_schema():
    from paper_search.review_projects import load_review_project

    path = Path("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    project = load_review_project(path)

    assert project.review_project_id == "multilingual-bias-benchmark-landscape"
    assert project.source_topic_slug == "bias-fairness"
    assert project.screening["confidence_threshold_for_human_review"] == 0.8
    assert any(field["name"] == "bias_type" for field in project.topic_schema)


def test_load_review_project_parses_new_topic_review_configs():
    from paper_search.review_projects import load_review_project

    conv = load_review_project("review_projects/examples/conversational-summarization-landscape.yaml")
    syco = load_review_project("review_projects/examples/sycophancy-evaluation-landscape.yaml")

    assert conv.source_topic_slug == "conv-summarization"
    assert any(field["name"] == "dialogue_domain" for field in conv.topic_schema)
    assert syco.source_topic_slug == "sycophancy"
    assert any(field["name"] == "setup_type" for field in syco.topic_schema)


def test_review_init_cli_creates_project_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    from paper_search.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["review-init", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"],
    )

    assert result.exit_code == 0, result.output
    state_path = tmp_path / "multilingual-bias-benchmark-landscape" / "state.json"
    assert state_path.exists()

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["review_project_id"] == "multilingual-bias-benchmark-landscape"
    assert state["stage"] == "initialized"


def test_review_screen_cli_writes_candidates_and_records(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    from paper_search.cli import main
    import paper_search.review_notion as review_notion
    import paper_search.review_screening as review_screening

    def fake_candidates(project, source="all", limit=None):
        return [
            {
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "topic_slug": project.source_topic_slug,
                "title": "A Multilingual Bias Benchmark",
                "abstract": "We introduce a multilingual benchmark for stereotype evaluation.",
                "summary": "**RQ**: ...",
                "source_url": "https://example.org/p1",
                "venue": "ACL",
                "source_label": "ACL",
            }
        ]

    def fake_screen(project, candidate):
        return {
            "decision": "include",
            "confidence": 0.93,
            "rationale": "Empirical multilingual benchmark paper.",
            "criteria_matched": ["empirical paper", "multilingual or cross-lingual setting"],
            "criteria_failed": [],
        }

    monkeypatch.setattr(review_notion, "load_review_candidates", fake_candidates)
    monkeypatch.setattr(review_screening, "screen_candidate", fake_screen)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "review-screen",
            "review_projects/examples/multilingual-bias-benchmark-landscape.yaml",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    candidates_path = review_dir / "candidates.jsonl"
    records_path = review_dir / "records.jsonl"
    state_path = review_dir / "state.json"

    assert candidates_path.exists()
    assert records_path.exists()
    assert state_path.exists()

    candidate_lines = [json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    record_lines = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert len(candidate_lines) == 1
    assert len(record_lines) == 1
    assert record_lines[0]["screening_decision"] == "include"
    assert record_lines[0]["screening_confidence"] == 0.93
    assert state["stage"] == "screened"
    assert state["screened_count"] == 1


def test_review_screen_cli_resumes_without_duplicate_records(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "records.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo-1",
                "title": "Paper One",
                "topic_slug": "bias-fairness",
                "screening_decision": "include",
                "screening_confidence": 0.91,
                "screening_rationale": "already screened",
                "criteria_matched": ["empirical paper"],
                "criteria_failed": [],
                "review_status": "screened_include",
                "human_override": None
            }
        ) + "\n",
        encoding="utf-8",
    )

    from paper_search.cli import main
    import paper_search.review_notion as review_notion
    import paper_search.review_screening as review_screening

    def fake_candidates(project, source="all", limit=None):
        return [
            {
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo-1",
                "topic_slug": project.source_topic_slug,
                "title": "Paper One",
                "abstract": "Already screened.",
                "summary": "",
                "source_url": "https://example.org/1",
                "venue": "ACL",
                "source_label": "ACL",
            },
            {
                "notion_page_id": "page-2",
                "paper_id": "2025-smith-demo-2",
                "topic_slug": project.source_topic_slug,
                "title": "Paper Two",
                "abstract": "New candidate.",
                "summary": "",
                "source_url": "https://example.org/2",
                "venue": "ACL",
                "source_label": "ACL",
            },
        ]

    def fake_screen(project, candidate):
        return {
            "decision": "exclude",
            "confidence": 0.8,
            "rationale": f"screened {candidate['title']}",
            "criteria_matched": [],
            "criteria_failed": ["multilingual or cross-lingual setting"],
        }

    monkeypatch.setattr(review_notion, "load_review_candidates", fake_candidates)
    monkeypatch.setattr(review_screening, "screen_candidate", fake_screen)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["review-screen", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"],
    )

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in (review_dir / 'records.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(lines) == 2
    assert sorted(r['notion_page_id'] for r in lines) == ['page-1', 'page-2']


def test_review_screen_cli_deduplicates_same_paper_across_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    from paper_search.cli import main
    import paper_search.review_notion as review_notion
    import paper_search.review_screening as review_screening

    def fake_candidates(project, source="all", limit=None):
        return [
            {
                "notion_page_id": "page-1",
                "paper_id": "2025-demo-paper",
                "topic_slug": project.source_topic_slug,
                "title": "Demo Paper",
                "abstract": "Multilingual benchmark paper.",
                "summary": "",
                "source_url": "https://example.org/1",
                "venue": "ACL",
                "source_label": "ACL",
            },
            {
                "notion_page_id": "page-2",
                "paper_id": "2025-demo-paper",
                "topic_slug": project.source_topic_slug,
                "title": "Demo Paper",
                "abstract": "Multilingual benchmark paper duplicated in another source.",
                "summary": "",
                "source_url": "https://example.org/2",
                "venue": "arXiv",
                "source_label": "arxiv",
            },
        ]

    def fake_screen(project, candidate):
        return {
            "decision": "include",
            "confidence": 0.9,
            "rationale": "screen once",
            "criteria_matched": ["multilingual or cross-lingual setting"],
            "criteria_failed": [],
        }

    monkeypatch.setattr(review_notion, "load_review_candidates", fake_candidates)
    monkeypatch.setattr(review_screening, "screen_candidate", fake_screen)

    runner = CliRunner()
    result = runner.invoke(main, ["review-screen", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"])
    assert result.exit_code == 0, result.output

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    lines = [json.loads(line) for line in (review_dir / 'records.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]['paper_id'] == '2025-demo-paper'


def test_screen_candidate_fast_excludes_non_multilingual_without_llm(monkeypatch):
    from paper_search.review_projects import load_review_project
    import paper_search.review_screening as review_screening

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    candidate = {
        "title": "Bias Mitigation in LLMs",
        "abstract": "We mitigate bias on English BBQ and StereoSet benchmarks.",
        "summary": "English-only benchmark evaluation with no cross-lingual setup.",
        "zh_brief": "",
        "paper_limitations": [],
    }

    def fail_get_client():
        raise AssertionError("LLM should not be called for obvious non-multilingual candidates")

    monkeypatch.setattr(review_screening, "get_llm_client", fail_get_client)
    result = review_screening.screen_candidate(project, candidate)

    assert result["decision"] == "exclude"
    assert "multilingual" in result["criteria_failed"][0]
    assert result["confidence"] >= 0.9


def test_screen_candidate_fast_includes_clear_multilingual_benchmark_without_llm(monkeypatch):
    from paper_search.review_projects import load_review_project
    import paper_search.review_screening as review_screening

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    candidate = {
        "title": "CBBQ: A Chinese Bias Benchmark Dataset for LLMs",
        "abstract": "We introduce a Chinese bias benchmark dataset for evaluating social bias in large language models.",
        "summary": "Multilingual benchmark-style contribution with explicit dataset construction and evaluation.",
        "zh_brief": "",
        "paper_limitations": [],
    }

    def fail_get_client():
        raise AssertionError("LLM should not be called for obvious multilingual benchmark candidates")

    monkeypatch.setattr(review_screening, "get_llm_client", fail_get_client)
    result = review_screening.screen_candidate(project, candidate)

    assert result["decision"] == "include"
    assert result["confidence"] >= 0.9
    assert any('multilingual' in x or 'cross-lingual' in x for x in result['criteria_matched'])


def test_screen_candidate_fast_includes_clear_conv_summarization_without_llm(monkeypatch):
    from paper_search.review_projects import load_review_project
    import paper_search.review_screening as review_screening

    project = load_review_project("review_projects/examples/conversational-summarization-landscape.yaml")
    candidate = {
        "title": "DialoSumBench: A Benchmark for Conversational Summarization",
        "abstract": "We introduce a benchmark and evaluation suite for dialogue and meeting summarization.",
        "summary": "Empirical conversational summarization dataset and model comparison.",
        "zh_brief": "",
        "paper_limitations": [],
    }

    def fail_get_client():
        raise AssertionError("LLM should not be called for obvious conversational summarization candidates")

    monkeypatch.setattr(review_screening, "get_llm_client", fail_get_client)
    result = review_screening.screen_candidate(project, candidate)

    assert result["decision"] == "include"
    assert result["confidence"] >= 0.9
    assert any('conversational' in x or 'dialogue' in x for x in result['criteria_matched'])


def test_fast_extract_multilingual_bias_filters_generic_benchmark_names():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "Safety of LLMs Beyond English: Systematic Review of Risks, Biases, and Safeguards",
        "abstract": "This systematic review analyzes multilingual benchmarks and evaluation gaps.",
        "summary": "The paper reviews multilingual benchmarks but does not introduce a named benchmark.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert extraction["benchmark_name"] is None


def test_fast_extract_multilingual_bias_multilingual_scope_does_not_force_language_count_one():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "Safety of LLMs Beyond English: Systematic Review of Risks, Biases, and Safeguards",
        "abstract": "This systematic review analyzes multilingual benchmarks and evaluation gaps.",
        "summary": "The paper studies systems beyond English without enumerating all languages.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert extraction["language_scope"] == "multilingual"
    assert extraction["language_count"] is None


def test_fast_extract_multilingual_bias_does_not_treat_long_title_prefix_as_benchmark():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "Safety of LLMs Beyond English: Systematic Review of Risks, Biases, and Safeguards",
        "abstract": "We discuss multilingual dataset and benchmark design gaps.",
        "summary": "This paper is a review and does not introduce a named benchmark.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert extraction["benchmark_name"] is None


def test_fast_extract_multilingual_bias_named_benchmark_is_not_misclassified_as_survey():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "CBBQ: A Chinese Bias Benchmark Dataset for LLMs (Human-AI Collaboration)",
        "abstract": "100K+ questions covering stereotypes and biases in 14 social dimensions related to Chinese culture and values.",
        "summary": "The authors introduce CBBQ, a Chinese Bias Benchmark dataset curated via human-AI collaboration.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert extraction["paper_type"] == "benchmark"
    assert extraction["benchmark_role"] == "introduces_benchmark"


def test_fast_extract_multilingual_bias_recognizes_positional_bias():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "PoSum-Bench: Benchmarking Position Bias in LLM-based Conversational Summarization",
        "abstract": "Large language models often exhibit positional bias in zero-shot conversation summarization.",
        "summary": "This benchmark evaluates positional bias across multilingual or cross-lingual settings.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert extraction["bias_type"] == "positional_bias"
    assert extraction["paper_type"] != "survey"


def test_fast_extract_multilingual_bias_uses_explicit_language_count_and_gender_bias_signals():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "What the Harm? Quantifying the Tangible Impact of Gender Bias in Machine Translation with a Human-centered Study",
        "abstract": "We study gender bias in machine translation across 3 languages with human-centered evaluation.",
        "summary": "This multilingual benchmark compares systems across 3 languages.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert extraction["bias_type"] == "stereotype"
    assert extraction["language_scope"] == "multilingual"
    assert extraction["language_count"] == 3


def test_fast_extract_multilingual_bias_does_not_false_match_indic_inside_other_words():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "KoBBQ: Korean Bias Benchmark for Question Answering",
        "abstract": "This paper studies a Korean benchmark and compares against English baselines using indirect prompting.",
        "summary": "The benchmark is for Korean question answering.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    extraction = extract_record(project, record)
    assert "indic" not in extraction["languages"]


def test_fast_extract_sycophancy_returns_structured_fields():
    from paper_search.review_projects import load_review_project
    from paper_search.review_extraction import extract_record

    project = load_review_project("review_projects/examples/sycophancy-evaluation-landscape.yaml")
    record = {
        "title": "SycEval: Benchmarking Sycophancy in Large Language Models",
        "abstract": "We introduce a benchmark for measuring whether LLMs mirror user beliefs and show reward-hacking tendencies after RLHF.",
        "summary": "The paper evaluates user-opinion conditioning and proposes mitigation baselines.",
        "zh_brief": "",
        "screening_rationale": "Clearly about sycophancy evaluation.",
    }

    extraction = extract_record(project, record)
    assert extraction["paper_type"] == "benchmark"
    assert extraction["evaluation_target"] in {"measurement", "mitigation"}
    assert extraction["feedback_loop_involved"] is True
    assert extraction["relevance_to_sycophancy_work"] == "high"


def test_hybrid_conv_fallback_overrides_evaluation_focus(monkeypatch):
    from paper_search.review_projects import load_review_project
    import paper_search.review_extraction as review_extraction

    monkeypatch.setenv("PAPER_SEARCH_REVIEW_EXTRACTION_MODEL", "qwen/qwen-2.5-72b-instruct")
    project = load_review_project("review_projects/examples/conversational-summarization-landscape.yaml")
    record = {
        "title": "A Meeting Summarization Study",
        "abstract": "We evaluate factuality and faithfulness in meeting summarization.",
        "summary": "The main focus is hallucination and faithfulness.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    monkeypatch.setattr(
        review_extraction,
        "_llm_fallback_extract",
        lambda project, record, max_retries=3: {"evaluation_focus": "faithfulness", "paper_type": "method"},
    )

    extraction = review_extraction.extract_record(project, record)
    assert extraction["evaluation_focus"] == "faithfulness"
    assert extraction["paper_type"] == "method"


def test_hybrid_bias_fallback_updates_only_selected_fields(monkeypatch):
    from paper_search.review_projects import load_review_project
    import paper_search.review_extraction as review_extraction

    monkeypatch.setenv("PAPER_SEARCH_REVIEW_EXTRACTION_MODEL", "qwen/qwen-2.5-72b-instruct")
    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "title": "BasqBBQ: QA Benchmark for Social Biases in LLMs for Basque",
        "abstract": "First BBQ benchmark for Basque and English across eight bias domains, evaluating multilingual models.",
        "summary": "Introduces BasqBBQ and includes human evaluation notes.",
        "zh_brief": "",
        "screening_rationale": "In scope.",
    }

    monkeypatch.setattr(
        review_extraction,
        "_llm_fallback_extract",
        lambda project, record, max_retries=3: {
            "benchmark_name": "basqbbq",
            "human_evaluation_used": True,
            "paper_type": "survey",
            "language_scope": "monolingual",
        },
    )

    extraction = review_extraction.extract_record(project, record)
    assert extraction["benchmark_name"] == "basqbbq"
    assert extraction["human_evaluation_used"] is True
    assert extraction["paper_type"] == "benchmark"
    assert extraction["language_scope"] == "multilingual"


def test_synthesis_fallback_uses_bias_research_question_template(monkeypatch):
    from paper_search.review_projects import load_review_project
    from paper_search.review_synthesis import synthesize_review
    import paper_search.review_synthesis as review_synthesis

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    rows = [
        {
            "title": "CBBQ: A Chinese Bias Benchmark Dataset for LLMs",
            "screening_rationale": "In scope.",
            "extraction": {
                "benchmark_name": "CBBQ",
                "language_scope": "multilingual",
                "paper_type": "benchmark",
                "review_gap_tags": ["translation-based dataset construction"],
            },
        }
    ]

    def fail_get_client():
        raise RuntimeError("force fallback")

    monkeypatch.setattr(review_synthesis, "get_llm_client", fail_get_client)
    synthesis = synthesize_review(project, rows)
    assert "## Benchmark families and language coverage" in synthesis
    assert "## Research ideas for FrenchBBQ / unified multilingual BBQ" in synthesis
    assert "CBBQ" in synthesis


def test_synthesis_fallback_uses_sycophancy_template(monkeypatch):
    from paper_search.review_projects import load_review_project
    from paper_search.review_synthesis import synthesize_review
    import paper_search.review_synthesis as review_synthesis

    project = load_review_project("review_projects/examples/sycophancy-evaluation-landscape.yaml")
    rows = [
        {
            "title": "SycEval",
            "screening_rationale": "In scope.",
            "extraction": {
                "benchmark_name": "SycEval",
                "paper_type": "benchmark",
                "review_gap_tags": ["RLHF-induced sycophancy mechanism"],
            },
        }
    ]

    def fail_get_client():
        raise RuntimeError("force fallback")

    monkeypatch.setattr(review_synthesis, "get_llm_client", fail_get_client)
    synthesis = synthesize_review(project, rows)
    assert "## How sycophancy is operationalized" in synthesis
    assert "## Research ideas worth testing" in synthesis
    assert "SycEval" in synthesis


def test_build_page_properties_surfaces_priority_notion_fields_and_research_summary():
    from paper_search.review_projects import load_review_project
    from paper_search.review_writeback import _build_page_properties

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    record = {
        "review_project_id": project.review_project_id,
        "title": "PoSum-Bench: Positional Bias Beyond English",
        "review_status": "extracted",
        "screening_confidence": 0.91,
        "screening_rationale": "Fast-screened as in scope because this paper introduces a relevant benchmark.",
    }
    extraction = {
        "paper_type": "benchmark",
        "benchmark_role": "introduces_benchmark",
        "benchmark_name": "posum-bench",
        "language_scope": "multilingual",
        "bias_type": "positional_bias",
        "translation_based": True,
        "cross_lingual_comparison_present": True,
        "human_evaluation_used": True,
        "language_count": 4,
        "relevance_to_frenchbbq": "high",
        "relevance_to_multilingual_unified_bbq": "high",
    }

    props = _build_page_properties(record, extraction, project=project)
    summary = props["Review Summary"]["rich_text"][0]["text"]["content"]
    idea = props["Idea Slate"]["rich_text"][0]["text"]["content"]

    assert summary != idea
    assert props["Benchmark Role"]["select"]["name"] == "introduces_benchmark"
    assert props["Translation Based"]["checkbox"] is True
    assert props["Cross-Lingual Comparison"]["checkbox"] is True
    assert props["Human Evaluation Used"]["checkbox"] is True
    assert props["FrenchBBQ Relevance"]["select"]["name"] == "high"
    assert props["Unified Multilingual BBQ Relevance"]["select"]["name"] == "high"
    assert props["Language Count"]["number"] == 4
    assert "introduces" in summary.lower()
    assert "benchmark 'posum-bench'" in summary.lower()
    assert "frenchbbq relevance is high" in summary.lower()

    assert "positional bias" in idea.lower() or "benchmark axis" in idea.lower()


def test_write_review_results_to_notion_updates_page_properties_and_research_card(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "records.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "title": "DemoBench: A Multilingual Bias Benchmark",
                "screening_decision": "include",
                "screening_confidence": 0.93,
                "screening_rationale": "Empirical multilingual benchmark paper.",
                "review_status": "screened_include",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_dir / "extractions.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "title": "DemoBench: A Multilingual Bias Benchmark",
                "review_status": "extracted",
                "extraction": {
                    "benchmark_role": "introduces_benchmark",
                    "benchmark_name": "DemoBench",
                    "language_scope": "multilingual",
                    "language_count": 3,
                    "bias_type": "stereotype",
                    "translation_based": True,
                    "cross_lingual_comparison_present": True,
                    "human_evaluation_used": False,
                    "relevance_to_frenchbbq": "medium",
                    "relevance_to_multilingual_unified_bbq": "high",
                    "review_gap_tags": ["translation-based dataset construction"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from paper_search.review_projects import load_review_project
    import paper_search.review_writeback as review_writeback

    class FakeChildren:
        def __init__(self):
            self.append_calls = []
            self.list_calls = []

        def list(self, block_id, page_size=100):
            self.list_calls.append((block_id, page_size))
            return {
                "results": [
                    {
                        "id": "old-card",
                        "type": "toggle",
                        "toggle": {
                            "rich_text": [
                                {"type": "text", "text": {"content": "Research Review Card"}, "plain_text": "Research Review Card"}
                            ]
                        },
                    }
                ]
            }

        def append(self, block_id, children):
            self.append_calls.append({"block_id": block_id, "children": children})

    class FakeBlocks:
        def __init__(self):
            self.children = FakeChildren()
            self.deleted = []

        def delete(self, block_id):
            self.deleted.append(block_id)

    class FakePages:
        def __init__(self):
            self.updates = []

        def update(self, page_id, properties):
            self.updates.append({"page_id": page_id, "properties": properties})

    class FakeNotionClient:
        def __init__(self):
            self.pages = FakePages()
            self.blocks = FakeBlocks()

    fake_client = FakeNotionClient()
    monkeypatch.setattr(review_writeback, "get_notion_client", lambda: fake_client)

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    result = review_writeback.write_review_results_to_notion(project)

    assert result == {"updated": 1, "skipped": 0}
    assert fake_client.pages.updates[0]["page_id"] == "page-1"
    props = fake_client.pages.updates[0]["properties"]
    assert props["Review Status"]["select"]["name"] == "extracted"
    assert props["Benchmark Role"]["select"]["name"] == "introduces_benchmark"
    assert props["Translation Based"]["checkbox"] is True
    assert props["FrenchBBQ Relevance"]["select"]["name"] == "medium"
    assert fake_client.blocks.deleted == ["old-card"]
    assert len(fake_client.blocks.children.append_calls) == 1
    card = fake_client.blocks.children.append_calls[0]["children"][0]
    assert card["type"] == "toggle"
    assert card["toggle"]["rich_text"][0]["text"]["content"] == "Research Review Card"
    child_text = json.dumps(card)
    assert "Research-use summary" in child_text
    assert "Structured extraction highlights" in child_text
    assert "Benchmark-design hook" in child_text


def test_generate_idea_slate_fallback_contains_candidate_ideas(monkeypatch):
    from paper_search.review_projects import load_review_project
    from paper_search.review_ideas import generate_idea_slate
    import paper_search.review_ideas as review_ideas

    project = load_review_project("review_projects/examples/conversational-summarization-landscape.yaml")
    rows = [
        {
            "title": "MeetingBank",
            "screening_rationale": "In scope.",
            "extraction": {
                "benchmark_name": "MeetingBank",
                "paper_type": "benchmark",
                "review_gap_tags": ["faithfulness underexplored"],
            },
        }
    ]

    def fail_get_client():
        raise RuntimeError("force fallback")

    monkeypatch.setattr(review_ideas, "get_llm_client", fail_get_client)
    slate = generate_idea_slate(project, rows, synthesis_text="# Review Synthesis\n")
    assert "# Idea Slate" in slate
    assert "## Candidate ideas" in slate
    assert "### Idea 1" in slate
    assert "MeetingBank" in slate


def test_review_extract_cli_writes_extractions(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "records.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "title": "A Multilingual Bias Benchmark",
                "topic_slug": "bias-fairness",
                "screening_decision": "include",
                "screening_confidence": 0.93,
                "screening_rationale": "Empirical multilingual benchmark paper.",
                "criteria_matched": ["empirical paper"],
                "criteria_failed": [],
                "review_status": "screened_include",
                "human_override": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_dir / "state.json").write_text(
        json.dumps({"review_project_id": "multilingual-bias-benchmark-landscape", "stage": "screened"}),
        encoding="utf-8",
    )

    from paper_search.cli import main
    import paper_search.review_extraction as review_extraction

    def fake_extract(project, record):
        return {
            "paper_type": "benchmark",
            "bias_type": "stereotype",
            "benchmark_name": "DemoBench",
            "language_scope": "multilingual",
            "languages": ["en", "fr"],
            "language_count": 2,
            "translation_based": True,
        }

    monkeypatch.setattr(review_extraction, "extract_record", fake_extract)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["review-extract", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"],
    )

    assert result.exit_code == 0, result.output
    extractions_path = review_dir / "extractions.jsonl"
    state = json.loads((review_dir / "state.json").read_text(encoding="utf-8"))
    extraction_lines = [json.loads(line) for line in extractions_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert extractions_path.exists()
    assert len(extraction_lines) == 1
    assert extraction_lines[0]["extraction"]["benchmark_name"] == "DemoBench"
    assert state["stage"] == "extracted"
    assert state["extracted_count"] == 1


def test_review_synthesize_cli_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "extractions.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "title": "A Multilingual Bias Benchmark",
                "screening_decision": "include",
                "extraction": {"benchmark_name": "DemoBench", "language_scope": "multilingual"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_dir / "state.json").write_text(
        json.dumps({"review_project_id": "multilingual-bias-benchmark-landscape", "stage": "extracted"}),
        encoding="utf-8",
    )

    from paper_search.cli import main
    import paper_search.review_synthesis as review_synthesis

    def fake_synthesize(project, rows):
        return "# Synthesis\n\n- Included papers: 1\n- DemoBench appears in the review.\n"

    monkeypatch.setattr(review_synthesis, "synthesize_review", fake_synthesize)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["review-synthesize", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"],
    )

    assert result.exit_code == 0, result.output
    synthesis_path = review_dir / "synthesis.md"
    state = json.loads((review_dir / "state.json").read_text(encoding="utf-8"))

    assert synthesis_path.exists()
    assert "DemoBench" in synthesis_path.read_text(encoding="utf-8")
    assert state["stage"] == "synthesized"


def test_review_queue_cli_writes_queue_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "extractions.jsonl").write_text(
        json.dumps(
            {
                "paper_id": "2025-smith-demo",
                "title": "A Multilingual Bias Benchmark",
                "year": "2025",
                "screening_confidence": 0.93,
                "extraction": {
                    "paper_type": "benchmark",
                    "benchmark_name": "DemoBench",
                    "benchmark_role": "introduces_benchmark",
                    "relevance_to_multilingual_unified_bbq": "high",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_dir / "state.json").write_text(json.dumps({"review_project_id": "multilingual-bias-benchmark-landscape"}), encoding="utf-8")

    from paper_search.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["review-queue", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"])
    assert result.exit_code == 0, result.output
    assert (review_dir / "reading_queue.jsonl").exists()
    assert (review_dir / "reading_queue.md").exists()
    assert "Read today" in (review_dir / "reading_queue.md").read_text(encoding="utf-8")


def test_review_gap_summary_cli_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "conversational-summarization-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "paper_id": "2025-smith-demo",
        "title": "A Faithfulness Study",
        "year": "2025",
        "screening_confidence": 0.9,
        "extraction": {
            "paper_type": "method",
            "dialogue_domain": "meeting",
            "input_modality": "speech_or_transcript",
            "evaluation_focus": "faithfulness",
            "llm_used": True,
            "multilingual_or_crosslingual": False,
            "streaming_or_real_time": False,
            "review_gap_tags": ["faithfulness underexplored"],
        },
    }
    (review_dir / "extractions.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (review_dir / "state.json").write_text(json.dumps({"review_project_id": "conversational-summarization-landscape"}), encoding="utf-8")

    from paper_search.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["review-gap-summary", "review_projects/examples/conversational-summarization-landscape.yaml"])
    assert result.exit_code == 0, result.output
    assert (review_dir / "gap_summary.md").exists()
    assert (review_dir / "topic_signals.json").exists()
    assert "Recurring gaps" in (review_dir / "gap_summary.md").read_text(encoding="utf-8")


def test_review_digest_cli_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "sycophancy-evaluation-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "paper_id": "2025-smith-demo",
        "title": "A Sycophancy Benchmark",
        "year": "2025",
        "screening_confidence": 0.91,
        "extraction": {
            "paper_type": "benchmark",
            "setup_type": "chat",
            "evaluation_target": "measurement",
            "user_opinion_conditioned": True,
            "feedback_loop_involved": True,
            "llm_used": True,
            "benchmark_or_dataset": True,
            "review_gap_tags": ["lack of standardized sycophancy benchmarks"],
        },
    }
    (review_dir / "extractions.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (review_dir / "synthesis.md").write_text("# Synthesis\n\nA benchmark-centered topic.\n", encoding="utf-8")
    (review_dir / "idea_slate.md").write_text("# Idea Slate\n\n- Core idea: Build a cleaner benchmark.\n", encoding="utf-8")
    (review_dir / "state.json").write_text(json.dumps({"review_project_id": "sycophancy-evaluation-landscape"}), encoding="utf-8")

    from paper_search.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["review-digest", "review_projects/examples/sycophancy-evaluation-landscape.yaml"])
    assert result.exit_code == 0, result.output
    assert (review_dir / "weekly_digest.md").exists()
    assert "Important papers to read first" in (review_dir / "weekly_digest.md").read_text(encoding="utf-8")


def test_review_obsidian_sync_writes_review_note_and_updates_paper_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))

    from paper_search.review_projects import load_review_project
    from paper_search.review_obsidian import sync_review_to_obsidian

    vault = tmp_path / "vault"
    papers_dir = vault / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / "2025-smith-demo.md").write_text(
        "---\ntitle: Demo\npaper_id: 2025-smith-demo\n---\n\n# Summary\n\nDemo body.\n",
        encoding="utf-8",
    )

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    records = [
        {
            "paper_id": "2025-smith-demo",
            "title": "A Multilingual Bias Benchmark",
            "screening_decision": "include",
            "screening_confidence": 0.93,
            "screening_rationale": "Empirical multilingual benchmark paper.",
        }
    ]
    extraction_rows = [
        {
            "paper_id": "2025-smith-demo",
            "title": "A Multilingual Bias Benchmark",
            "screening_decision": "include",
            "extraction": {
                "benchmark_name": "DemoBench",
                "benchmark_role": "introduces_benchmark",
                "language_scope": "multilingual",
                "bias_type": "stereotype",
                "relevance_to_multilingual_unified_bbq": "high",
            },
        }
    ]
    synthesis = "# Review Synthesis\n\nDemoBench is included.\n"

    paths = sync_review_to_obsidian(project, records, extraction_rows, synthesis)

    review_note = vault / "reviews" / "multilingual-bias-benchmark-landscape.md"
    paper_note = papers_dir / "2025-smith-demo.md"

    assert review_note.exists()
    assert paper_note.exists()
    map_note = vault / "reviews" / "multilingual-bias-benchmark-landscape-map.md"
    assert map_note.exists()
    assert "High-value unified multilingual BBQ references" in map_note.read_text(encoding="utf-8")
    assert "DemoBench" in review_note.read_text(encoding="utf-8")
    updated_note = paper_note.read_text(encoding="utf-8")
    assert "## Review sync" in updated_note
    assert "multilingual-bias-benchmark-landscape" in updated_note
    assert "benchmark_role: introduces_benchmark" in updated_note or "Benchmark role: `introduces_benchmark`" in updated_note
    assert "language_scope:\n- multilingual" in updated_note
    assert paths["review_note_path"] == str(review_note)


def test_review_obsidian_sync_creates_missing_note_and_aligns_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))

    from paper_search.review_projects import load_review_project
    from paper_search.review_obsidian import sync_review_to_obsidian

    project = load_review_project("review_projects/examples/multilingual-bias-benchmark-landscape.yaml")
    records = [
        {
            "paper_id": "2025-smith-demo-missing",
            "title": "Missing Demo Paper",
            "screening_decision": "include",
            "screening_confidence": 0.91,
            "screening_rationale": "Empirical multilingual benchmark paper.",
            "review_status": "extracted",
            "notion_page_id": "page-123",
            "source_url": "https://example.org/paper",
            "venue": "ACL",
            "year": 2025,
            "authors": ["Alice Smith"],
        }
    ]
    extraction_rows = [
        {
            "paper_id": "2025-smith-demo-missing",
            "title": "Missing Demo Paper",
            "screening_decision": "include",
            "review_status": "extracted",
            "extraction": {
                "benchmark_name": "DemoBench",
                "benchmark_role": "introduces_benchmark",
                "language_scope": "multilingual",
                "language_count": 3,
                "bias_type": "stereotype",
                "translation_based": True,
                "cross_lingual_comparison_present": True,
                "human_evaluation_used": False,
                "relevance_to_frenchbbq": "medium",
                "relevance_to_multilingual_unified_bbq": "high",
                "review_gap_tags": ["translation-based dataset construction"],
            },
        }
    ]

    paths = sync_review_to_obsidian(project, records, extraction_rows, "# Review Synthesis\n")
    note_path = tmp_path / "vault" / "papers" / "2025-smith-demo-missing.md"
    assert note_path.exists()
    text = note_path.read_text(encoding="utf-8")
    assert "benchmark_role: introduces_benchmark" in text
    assert "language_scope:\n- multilingual" in text
    assert "translation_based: true" in text.lower()
    assert "review_project_id: multilingual-bias-benchmark-landscape" in text
    assert "## Review sync" in text
    assert paths["created_paper_notes"] == [str(note_path)]


def test_review_writeback_cli_updates_notion_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "records.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "title": "A Multilingual Bias Benchmark",
                "screening_decision": "include",
                "screening_confidence": 0.93,
                "screening_rationale": "Empirical multilingual benchmark paper.",
                "review_status": "screened_include",
                "source_label": "ACL",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_dir / "extractions.jsonl").write_text(
        json.dumps(
            {
                "review_project_id": "multilingual-bias-benchmark-landscape",
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "title": "A Multilingual Bias Benchmark",
                "screening_decision": "include",
                "extraction": {
                    "relevance_to_multilingual_unified_bbq": "high",
                    "language_scope": "multilingual",
                    "bias_type": "stereotype"
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (review_dir / "state.json").write_text(
        json.dumps({"review_project_id": "multilingual-bias-benchmark-landscape", "stage": "synthesized"}),
        encoding="utf-8",
    )

    from paper_search.cli import main
    import paper_search.review_writeback as review_writeback

    calls = {"ensure": [], "update": []}

    def fake_ensure(project, source_labels=None):
        calls["ensure"].append(sorted(source_labels or []))

    def fake_writeback(project):
        calls["update"].append(project.review_project_id)
        return {"updated": 1, "skipped": 0}

    monkeypatch.setattr(review_writeback, "ensure_review_properties", fake_ensure)
    monkeypatch.setattr(review_writeback, "write_review_results_to_notion", fake_writeback)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["review-writeback", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml"],
    )

    assert result.exit_code == 0, result.output
    assert calls["ensure"] == [["ACL"]]
    assert calls["update"] == ["multilingual-bias-benchmark-landscape"]


def test_review_run_cli_executes_screen_extract_synthesize_ideas_and_writeback(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SEARCH_REVIEW_CACHE_DIR", str(tmp_path))

    from paper_search.cli import main
    import paper_search.review_notion as review_notion
    import paper_search.review_screening as review_screening
    import paper_search.review_extraction as review_extraction
    import paper_search.review_synthesis as review_synthesis
    import paper_search.review_ideas as review_ideas
    import paper_search.review_writeback as review_writeback
    import paper_search.review_obsidian as review_obsidian

    def fake_candidates(project, source="all", limit=None):
        return [
            {
                "notion_page_id": "page-1",
                "paper_id": "2025-smith-demo",
                "topic_slug": project.source_topic_slug,
                "title": "A Multilingual Bias Benchmark",
                "abstract": "We introduce a multilingual benchmark for stereotype evaluation.",
                "summary": "**RQ**: ...",
                "source_url": "https://example.org/p1",
                "venue": "ACL",
                "source_label": "ACL",
            }
        ]

    def fake_screen(project, candidate):
        return {
            "decision": "include",
            "confidence": 0.93,
            "rationale": "Empirical multilingual benchmark paper.",
            "criteria_matched": ["empirical paper", "multilingual or cross-lingual setting"],
            "criteria_failed": [],
        }

    def fake_extract(project, record):
        return {
            "paper_type": "benchmark",
            "benchmark_name": "DemoBench",
            "language_scope": "multilingual",
        }

    def fake_synthesize(project, rows):
        return "# Synthesis\n\nDemoBench is included.\n"

    def fake_ideas(project, rows, synthesis_text, gap_summary_text=""):
        return "# Idea Slate\n\n## Candidate ideas\n\n### Idea 1\n- Core idea: Demo idea.\n"

    calls = {"ensure": [], "update": []}

    def fake_ensure(project, source_labels=None):
        calls["ensure"].append(sorted(source_labels or []))

    def fake_writeback(project):
        calls["update"].append(project.review_project_id)
        return {"updated": 1, "skipped": 0}

    def fake_obsidian_sync(project, records, extraction_rows, synthesis_text, idea_slate_text="", gap_summary_text="", reading_queue_text="", digest_text=""):
        calls["obsidian"] = {
            "project": project.review_project_id,
            "records": len(records),
            "extractions": len(extraction_rows),
            "has_idea_slate": bool(idea_slate_text.strip()),
            "has_gap_summary": bool(gap_summary_text.strip()),
            "has_reading_queue": bool(reading_queue_text.strip()),
            "has_digest": bool(digest_text.strip()),
        }
        return {"review_note_path": "/tmp/review.md", "updated_paper_notes": ["/tmp/paper.md"]}

    monkeypatch.setattr(review_notion, "load_review_candidates", fake_candidates)
    monkeypatch.setattr(review_screening, "screen_candidate", fake_screen)
    monkeypatch.setattr(review_extraction, "extract_record", fake_extract)
    monkeypatch.setattr(review_synthesis, "synthesize_review", fake_synthesize)
    monkeypatch.setattr(review_ideas, "generate_idea_slate", fake_ideas)
    monkeypatch.setattr(review_writeback, "ensure_review_properties", fake_ensure)
    monkeypatch.setattr(review_writeback, "write_review_results_to_notion", fake_writeback)
    monkeypatch.setattr(review_obsidian, "sync_review_to_obsidian", fake_obsidian_sync)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["review-run", "review_projects/examples/multilingual-bias-benchmark-landscape.yaml", "--limit", "1"],
    )

    assert result.exit_code == 0, result.output
    review_dir = tmp_path / "multilingual-bias-benchmark-landscape"
    state = json.loads((review_dir / "state.json").read_text(encoding="utf-8"))

    assert (review_dir / "candidates.jsonl").exists()
    assert (review_dir / "records.jsonl").exists()
    assert (review_dir / "extractions.jsonl").exists()
    assert (review_dir / "reading_queue.jsonl").exists()
    assert (review_dir / "reading_queue.md").exists()
    assert (review_dir / "synthesis.md").exists()
    assert (review_dir / "gap_summary.md").exists()
    assert (review_dir / "topic_signals.json").exists()
    assert (review_dir / "weekly_digest.md").exists()
    assert (review_dir / "idea_slate.md").exists()
    assert state["stage"] == "obsidian_synced"
    assert calls["ensure"] == [["ACL"]]
    assert calls["update"] == ["multilingual-bias-benchmark-landscape"]
    assert calls["obsidian"] == {
        "project": "multilingual-bias-benchmark-landscape",
        "records": 1,
        "extractions": 1,
        "has_idea_slate": True,
        "has_gap_summary": True,
        "has_reading_queue": True,
        "has_digest": True,
    }
