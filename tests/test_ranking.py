"""Tests for query intent, scoring, re-ranking, and variant building (T04/T05)."""
from __future__ import annotations

from adapter.ranking import (
    build_variant_query,
    detect_intent,
    extract_entities,
    has_sufficient_quality,
    rerank_results,
)


def test_extract_entities_keeps_compound_terms():
    entities = extract_entities("agent-browser session-name cookie persistence")
    assert "agent-browser" in entities
    assert "session-name" in entities


def test_extract_entities_quoted_phrase_first():
    entities = extract_entities('"agent-browser" "session-name"')
    assert entities[0] == "agent-browser"
    assert entities[1] == "session-name"


def test_extract_entities_cjk_bigrams():
    entities = extract_entities("杭州西湖景区预约")
    # 长 CJK 片段切成 bigram，避免整句无法匹配
    assert any("西湖" in e for e in entities)


def test_detect_intent_official():
    assert "official" in detect_intent("uv pip compile documentation")
    assert "official" in detect_intent("杭州 西湖 预约 官方")
    assert "official" not in detect_intent("python list sort")


def test_rerank_prefers_topical_page_with_entity_match():
    results = [
        {"title": "UV Index Los Angeles", "url": "https://uvi.today/la", "content": "uv index"},
        {
            "title": "Locking environments | uv",
            "url": "https://docs.astral.sh/uv/pip/compile/",
            "content": "uv pip compile requirements lockfile",
        },
    ]
    ranked = rerank_results(results, "uv pip compile generate lockfile documentation")
    assert ranked[0].item["url"] == "https://docs.astral.sh/uv/pip/compile/"
    assert ranked[0].score > ranked[1].score
    assert ranked[0].reasons  # 打分理由可解释


def test_rerank_official_intent_boosts_docs_host():
    results = [
        {"title": "agent tools blog", "url": "https://blog.example.com/agent-browser", "content": "agent-browser session-name"},
        {"title": "agent-browser sessions", "url": "https://agent-browser.dev/sessions", "content": "session-name"},
    ]
    ranked = rerank_results(results, "agent-browser session-name official documentation")
    assert ranked[0].item["url"] == "https://agent-browser.dev/sessions"


def test_rerank_limits_per_host_diversity():
    results = [
        {"title": "a python asyncio", "url": "https://docs.python.org/a", "content": "asyncio"},
        {"title": "b python asyncio", "url": "https://docs.python.org/b", "content": "asyncio"},
        {"title": "c python asyncio", "url": "https://docs.python.org/c", "content": "asyncio"},
        {"title": "d python asyncio", "url": "https://other.example.com/d", "content": "asyncio"},
    ]
    ranked = rerank_results(results, "python asyncio", max_per_host=2)
    # 第三名同站结果沉底，但不删除
    assert ranked[2].item["url"] == "https://other.example.com/d"
    assert len(ranked) == 4


def test_has_sufficient_quality():
    good = rerank_results(
        [{"title": "uv pip compile", "url": "https://docs.astral.sh/uv/pip/compile/", "content": "uv pip compile lockfile"}],
        "uv pip compile documentation",
    )
    assert has_sufficient_quality(good, 1) is True
    bad = rerank_results(
        [{"title": "unrelated", "url": "https://x.example.com", "content": "nothing"}],
        "uv pip compile documentation",
    )
    assert has_sufficient_quality(bad, 1) is False
    assert has_sufficient_quality([], 1) is False


def test_build_variant_query_quotes_distinctive_terms():
    variant = build_variant_query("agent-browser session-name cookie persistence")
    assert variant is not None
    assert '"agent-browser"' in variant
    assert '"session-name"' in variant


def test_build_variant_query_skips_quoted_or_simple():
    assert build_variant_query('"already" "quoted"') is None
    assert build_variant_query("python") is None
    assert build_variant_query("杭州西湖预约") is None


def test_extract_entities_keeps_short_product_names():
    """uv、go 等短产品名是核心实体，不能按长度丢弃。"""
    entities = extract_entities("uv pip compile generate lockfile documentation")
    assert "uv" in entities
    assert "pip" in entities


def test_short_entity_word_boundary_matching():
    """短实体用词边界匹配：uv 命中 /uv/ 页面，不命中 uvi.today。"""
    results = [
        {"title": "UV Index Los Angeles", "url": "https://uvi.today/la", "content": "uv index forecast"},
        {
            "title": "Locking environments | uv",
            "url": "https://docs.astral.sh/uv/pip/compile/",
            "content": "uv pip compile requirements lockfile",
        },
    ]
    ranked = rerank_results(results, "uv pip compile generate lockfile documentation")
    assert ranked[0].item["url"] == "https://docs.astral.sh/uv/pip/compile/"


def test_build_variant_prefers_product_names_over_generic_words():
    variant = build_variant_query("uv pip compile generate lockfile documentation")
    assert variant is not None
    assert '"uv"' in variant
    assert '"documentation"' not in variant
