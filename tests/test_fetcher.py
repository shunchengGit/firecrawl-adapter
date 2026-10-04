"""Tests for fetcher layer: filtering, classification, PDF, headless wait (offline)."""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from unittest.mock import patch

from adapter import fetcher
from adapter.config import config
from adapter.fetcher import (
    SCRAPE_INCOMPLETE,
    SCRAPE_NOT_FOUND,
    SCRAPE_OK,
    SCRAPE_RESTRICTED,
    SCRAPE_UNSUPPORTED,
    classify_html,
    filter_results,
    normalize_domain,
    normalize_url_key,
    scrape_url_result,
)

# ---------------------------------------------------------------------------
# T03: 域名硬过滤与去重
# ---------------------------------------------------------------------------


def test_normalize_domain():
    assert normalize_domain("Docs.Astral.sh") == "docs.astral.sh"
    assert normalize_domain("https://docs.astral.sh/uv/") == "docs.astral.sh"
    assert normalize_domain("docs.astral.sh:443") == "docs.astral.sh"


def test_normalize_url_key_strips_fragment_and_default_port():
    a = normalize_url_key("https://example.com:443/page#section")
    b = normalize_url_key("https://example.com/page")
    assert a == b
    # query 保留：不同参数不合并
    assert normalize_url_key("https://example.com/p?a=1") != normalize_url_key(
        "https://example.com/p?a=2"
    )


def test_filter_results_include_domains_hard_constraint():
    results = [
        {"title": "a", "url": "https://docs.astral.sh/uv/", "content": ""},
        {"title": "b", "url": "https://uvi.today/uv-index", "content": ""},
    ]
    filtered = filter_results(results, include_domains=["docs.astral.sh"])
    assert [r["url"] for r in filtered] == ["https://docs.astral.sh/uv/"]


def test_filter_results_subdomain_rules():
    results = [
        {"title": "sub", "url": "https://docs.astral.sh/uv/", "content": ""},
        {"title": "root", "url": "https://astral.sh/", "content": ""},
        # hostname 包含字样但实际属于其他域名，不得通过
        {"title": "evil", "url": "https://docs.astral.sh.evil.com/x", "content": ""},
    ]
    filtered = filter_results(results, include_domains=["astral.sh"])
    urls = [r["url"] for r in filtered]
    assert "https://docs.astral.sh/uv/" in urls
    assert "https://astral.sh/" in urls
    assert "https://docs.astral.sh.evil.com/x" not in urls


def test_filter_results_exclude_wins_over_include():
    results = [
        {"title": "a", "url": "https://blog.example.com/post", "content": ""},
        {"title": "b", "url": "https://www.example.com/page", "content": ""},
    ]
    filtered = filter_results(
        results, include_domains=["example.com"], exclude_domains=["blog.example.com"]
    )
    assert [r["url"] for r in filtered] == ["https://www.example.com/page"]


def test_filter_results_rejects_bad_urls_and_dedupes():
    results = [
        {"title": "ok", "url": "https://example.com/page#frag", "content": ""},
        {"title": "dup", "url": "https://example.com/page", "content": ""},
        {"title": "ftp", "url": "ftp://example.com/file", "content": ""},
        {"title": "no scheme", "url": "example.com/page", "content": ""},
        {"title": "empty", "url": "", "content": ""},
        "not-a-dict",
    ]
    filtered = filter_results(results)
    assert [r["url"] for r in filtered] == ["https://example.com/page#frag"]


def test_filter_results_strips_internal_fields_from_public_items():
    results = [{"title": "a", "url": "https://example.com/", "content": "", "_engines": ["bing"]}]
    filtered = filter_results(results)
    assert "_engines" not in filtered[0]
    assert filtered[0]["_diag"]["_engines"] == ["bing"]


# ---------------------------------------------------------------------------
# T02: 引擎隔离配置
# ---------------------------------------------------------------------------


def test_effective_engines_applies_disabled_list():
    patched = dataclasses.replace(
        config, searxng_engines="bing,360search,yandex", searxng_disabled_engines="bing"
    )
    with patch("adapter.fetcher.config", patched):
        assert fetcher._effective_engines(None) == "360search,yandex"
        # 显式参数不受隔离配置影响
        assert fetcher._effective_engines("bing") == "bing"


# ---------------------------------------------------------------------------
# T06: 抓取有效性分类
# ---------------------------------------------------------------------------


def test_classify_hard_404():
    status, _ = classify_html("<html><body>anything</body></html>", http_status=404)
    assert status == SCRAPE_NOT_FOUND


def test_classify_soft_404_by_content():
    status, _ = classify_html("<html><body><p>页面不存在或已删除</p></body></html>")
    assert status == SCRAPE_NOT_FOUND


def test_classify_anti_bot_short_page():
    status, _ = classify_html("<html><body><p>请完成 captcha 验证后继续</p></body></html>")
    assert status == SCRAPE_RESTRICTED


def test_classify_long_article_mentioning_captcha_is_ok():
    body = "这是一篇讨论 captcha 技术原理的长文。" + "正文内容。" * 300
    status, _ = classify_html(f"<html><body><article>{body}</article></body></html>")
    assert status == SCRAPE_OK


def test_classify_spa_shell_incomplete():
    html = '<html><body><div id="root"></div><script src="/app.js"></script></body></html>'
    status, _ = classify_html(html)
    assert status == SCRAPE_INCOMPLETE


def test_classify_legit_short_page_ok():
    status, detail = classify_html("<html><body><p>Hi.</p></body></html>")
    assert status == SCRAPE_OK
    assert detail == "short page"


def test_scrape_result_hard_404_skips_headless():
    resp = SimpleNamespace(
        status_code=404,
        url="https://example.com/gone",
        headers={"content-type": "text/html"},
        content=b"<html><body>gone</body></html>",
        text="<html><body>gone</body></html>",
    )
    with (
        patch("adapter.fetcher.requests.get", return_value=resp),
        patch("adapter.fetcher.scrape_url_headless") as headless,
    ):
        result = scrape_url_result("https://example.com/gone")
    assert result.status == SCRAPE_NOT_FOUND
    headless.assert_not_called()


def test_scrape_result_403_falls_back_to_headless():
    resp = SimpleNamespace(
        status_code=403,
        url="https://example.com/protected",
        headers={"content-type": "text/html"},
        content=b"<html><body>forbidden</body></html>",
        text="<html><body>forbidden</body></html>",
    )
    good_html = "<html><body><article>" + "正文。" * 200 + "</article></body></html>"
    with (
        patch("adapter.fetcher.requests.get", return_value=resp),
        patch(
            "adapter.fetcher.scrape_url_headless",
            return_value=("https://example.com/protected", good_html, False),
        ),
    ):
        result = scrape_url_result("https://example.com/protected")
    assert result.status == SCRAPE_OK
    assert result.via == "agent-browser"
    assert result.document is not None
    assert result.document["metadata"]["scrapeStatus"] == SCRAPE_OK


def test_scrape_result_both_paths_fail_is_not_success():
    with (
        patch("adapter.fetcher.requests.get", side_effect=ConnectionError("refused")),
        patch("adapter.fetcher.scrape_url_headless", side_effect=RuntimeError("no browser")),
    ):
        result = scrape_url_result("https://example.com/")
    assert result.status == fetcher.SCRAPE_NETWORK_ERROR
    assert result.document is None
    assert "no browser" in result.detail


# ---------------------------------------------------------------------------
# T10: PDF
# ---------------------------------------------------------------------------


def _make_pdf(text: str) -> bytes:
    """手工构造一个含可提取文本的最小 PDF。"""
    content = f"BT /F1 24 Tf 100 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(content)).encode() + b">>stream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_is_pdf_detection():
    assert fetcher._is_pdf("application/pdf", b"anything")
    assert fetcher._is_pdf("application/octet-stream", b"%PDF-1.4 ...")
    assert not fetcher._is_pdf("text/html", b"<html>")


def test_pdf_text_extraction():
    data = _make_pdf("Dummy PDF file")
    result = fetcher._pdf_to_result(data, "https://example.com/x", "https://example.com/x")
    assert result.status == SCRAPE_OK
    assert result.document is not None
    assert "Dummy PDF file" in result.document["markdown"]
    assert result.document["metadata"]["contentType"] == "application/pdf"


def test_pdf_corrupt_is_unsupported():
    result = fetcher._pdf_to_result(b"%PDF-1.4 not really a pdf", "u", "u")
    assert result.status == SCRAPE_UNSUPPORTED


def test_pdf_too_large_is_unsupported():
    patched = dataclasses.replace(config, max_pdf_bytes=10)
    with patch("adapter.fetcher.config", patched):
        result = fetcher._pdf_to_result(_make_pdf("Dummy PDF file"), "u", "u")
    assert result.status == SCRAPE_UNSUPPORTED


def test_scrape_result_pdf_via_content_type():
    data = _make_pdf("Dummy PDF file")
    resp = SimpleNamespace(
        status_code=200,
        url="https://example.com/download",
        headers={"content-type": "application/pdf"},
        content=data,
    )
    with patch("adapter.fetcher.requests.get", return_value=resp):
        result = scrape_url_result("https://example.com/download")
    assert result.status == SCRAPE_OK
    assert "Dummy PDF file" in result.document["markdown"]


# ---------------------------------------------------------------------------
# T07: headless 正文就绪等待（受控时钟 + 浏览器 mock）
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class _FakeBrowserRun:
    """按脚本模拟 agent-browser：open/eval/get/close 子进程调用。"""

    def __init__(self, clock: _FakeClock, start: float, script, html: str):
        self.clock = clock
        self.start = start
        self.script = script  # fn(elapsed) -> (text_len, mutation_age_s)
        self.html = html
        self.probe_count = 0

    def __call__(self, args, **kwargs):
        cmd = args[3:]  # 跳过 [agent_bin, --session, session]
        if cmd[0] == "open":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "close":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "get":
            payload = {"data": {"url": "https://example.com/final"}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        if cmd[0] == "eval":
            expr = cmd[1]
            if expr == fetcher._OBSERVER_JS:
                return SimpleNamespace(returncode=0, stdout="'ok'", stderr="")
            if expr == fetcher._PROBE_JS:
                self.probe_count += 1
                elapsed = self.clock.t - self.start
                text_len, mutation_age = self.script(elapsed)
                m = (self.clock.t - mutation_age) * 1000
                return SimpleNamespace(
                    returncode=0, stdout=json.dumps({"t": text_len, "m": m}), stderr=""
                )
            return SimpleNamespace(returncode=0, stdout=self.html, stderr="")
        raise AssertionError(f"unexpected command: {cmd}")


def _run_headless(script, timeout: float, html: str = "<html><body>content</body></html>"):
    clock = _FakeClock()
    start = clock.t
    fake = _FakeBrowserRun(clock, start, script, html)
    with (
        patch("adapter.fetcher.find_agent_browser", return_value="/fake/agent-browser"),
        patch("adapter.fetcher.subprocess.run", side_effect=fake),
        patch("adapter.fetcher.time", clock),
    ):
        final_url, out_html, timed_out = fetcher.scrape_url_headless(
            "https://example.com/", timeout=timeout
        )
    return final_url, out_html, timed_out, fake


def test_headless_waits_for_delayed_content():
    """延迟 JS 页：正文 10 秒后才注入，等待后应拿到而不是立即读取导航壳。"""

    def script(elapsed: float):
        if elapsed < 10:
            return 89, 0  # 导航壳 + 持续变更
        return 1500, elapsed - 10  # 10 秒时注入正文

    final_url, html, timed_out, fake = _run_headless(script, timeout=30)
    assert timed_out is False
    assert final_url == "https://example.com/final"
    assert html == "<html><body>content</body></html>"
    # 真的等了：探针次数远多于立即读取
    assert fake.probe_count > 10


def test_headless_budget_exhausted_marks_timed_out():
    """预算不足时明确超时，不把导航壳当完整正文。"""

    def script(elapsed: float):
        return 89, 0  # 永远只有导航且持续变更

    _, _, timed_out, _ = _run_headless(script, timeout=8)
    assert timed_out is True


def test_headless_short_static_page_does_not_wait_forever():
    """合法短页面：DOM 长时间静默后不再空等，但要等满逃逸窗口。"""

    def script(elapsed: float):
        return 80, 999  # 很短但一直静默

    _, _, timed_out, fake = _run_headless(script, timeout=30)
    assert timed_out is False
    # budget*0.5=15s 逃逸：约 (15-2)/0.5=26 个探针，不耗满 30s 预算
    assert 15 <= fake.probe_count < 35


def test_headless_wait_for_parameter_enforces_minimum_wait():
    """waitFor（毫秒）语义：正文就绪前至少等待指定时长。"""

    def script(elapsed: float):
        return 500, 999  # 内容早已就绪且静默

    clock = _FakeClock()
    start = clock.t
    fake = _FakeBrowserRun(clock, start, script, "<html><body>x</body></html>")
    with (
        patch("adapter.fetcher.find_agent_browser", return_value="/fake/agent-browser"),
        patch("adapter.fetcher.subprocess.run", side_effect=fake),
        patch("adapter.fetcher.time", clock),
    ):
        _, _, timed_out = fetcher.scrape_url_headless(
            "https://example.com/", timeout=30, wait_ms=5000
        )
    assert timed_out is False
    assert clock.t - start >= 5.0  # waitFor=5000ms 被兑现而非静默忽略


def test_effective_engines_disabled_with_empty_config():
    """SEARXNG_ENGINES 未配置时，禁用列表基于模板默认引擎集做减法。"""
    patched = dataclasses.replace(config, searxng_engines="", searxng_disabled_engines="bing,quark")
    with patch("adapter.fetcher.config", patched):
        result = fetcher._effective_engines(None)
    assert result is not None
    assert "bing" not in result.split(",")
    assert "quark" not in result.split(",")
    assert "360search" in result.split(",")


def test_headless_short_page_escape_does_not_beat_delayed_injection():
    """短页逃逸必须晚于典型的延迟注入（10 秒级），否则仍会早读导航壳。"""

    def script(elapsed: float):
        if elapsed < 10:
            return 89, 999  # 导航壳，DOM 早已静默（安静≠加载完）
        return 1500, elapsed - 10

    _, html, timed_out, fake = _run_headless(script, timeout=30)
    # 逃逸点在 budget*0.5=15s，注入在 10s：应在注入后就绪，而不是逃逸读壳
    assert timed_out is False
    assert fake.probe_count < 26  # 约 11.5s 就绪，而不是耗到 15s 逃逸
