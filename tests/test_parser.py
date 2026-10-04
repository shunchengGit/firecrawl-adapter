"""Tests for parser helpers (pure functions)."""
from __future__ import annotations

from bs4 import BeautifulSoup

from adapter.parser import (
    compile_path_patterns,
    extract_main,
    get_meta,
    html_to_markdown,
    match_path,
)


def test_match_path_no_patterns_matches_all():
    assert match_path("https://example.com/any/path", None) is True
    assert match_path("https://example.com/any/path", ()) is True


def test_match_path_prefix_match():
    patterns = compile_path_patterns(("/blog",))
    assert match_path("https://example.com/blog/post-1", patterns) is True
    assert match_path("https://example.com/about", patterns) is False


def test_match_path_wildcard():
    patterns = compile_path_patterns(("/docs/*",))
    assert match_path("https://example.com/docs/2024/x", patterns) is True
    assert match_path("https://example.com/api/v1", patterns) is False


def test_match_path_regex_metacharacters_are_literal():
    patterns = compile_path_patterns(("/a.b+[](",))
    assert match_path("https://example.com/a.b+[](/child", patterns) is True
    assert match_path("https://example.com/axb", patterns) is False


def test_get_meta_by_name():
    html = '<html><head><meta name="description" content="hello world"></head><body></body></html>'
    soup = BeautifulSoup(html, "html.parser")
    assert get_meta(soup, "description") == "hello world"


def test_get_meta_by_og_property():
    html = '<html><head><meta property="og:description" content="og content"></head></html>'
    soup = BeautifulSoup(html, "html.parser")
    assert get_meta(soup, "description") == "og content"


def test_get_meta_missing_returns_empty():
    html = "<html><head></head></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert get_meta(soup, "description") == ""


def test_extract_main_finds_article():
    html = """
    <html><body>
      <header>nav</header>
      <article><p>main content here</p></article>
      <footer>foot</footer>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    main = extract_main(soup)
    assert main.name == "article"
    assert "main content here" in main.get_text()


def test_extract_main_falls_back_to_soup():
    html = "<html><body><p>no semantic tags</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert extract_main(soup) is soup


def test_html_to_markdown_truncates():
    html = "<p>" + ("a " * 1000) + "</p>"
    md = html_to_markdown(html, max_chars=50)
    assert len(md) <= 50


def test_html_to_markdown_basic():
    md = html_to_markdown("<h1>Title</h1><p>Body</p>", max_chars=1000)
    assert "Title" in md
    assert "Body" in md


# T08: Markdown 跨文档状态污染修复


def test_html_to_markdown_no_cross_document_state():
    """前一页的缩写定义不得残留到后一页（同线程连续转换）。"""
    md1 = html_to_markdown(
        '<p><abbr title="Only belongs to first page">FIRST_PAGE_TOKEN</abbr></p>',
        max_chars=10000,
    )
    assert "FIRST_PAGE_TOKEN" in md1
    md2 = html_to_markdown("<p>Second page plain content</p>", max_chars=10000)
    assert "FIRST_PAGE_TOKEN" not in md2
    assert "Only belongs to first page" not in md2


def test_html_to_markdown_repeat_conversion_is_stable():
    html = '<p><abbr title="Definition">TOKEN</abbr> text</p>'
    first = html_to_markdown(html, max_chars=10000)
    second = html_to_markdown(html, max_chars=10000)
    assert first == second


def test_html_to_markdown_concurrent_documents_isolated():
    """多线程并发转换互不串页。"""
    import threading

    outputs: dict[int, str] = {}

    def convert(i: int):
        outputs[i] = html_to_markdown(
            f'<p><abbr title="Def {i}">TOKEN_{i}</abbr></p>', max_chars=10000
        )

    threads = [threading.Thread(target=convert, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for i, md in outputs.items():
        assert f"TOKEN_{i}" in md
        for j in range(8):
            if j != i:
                assert f"TOKEN_{j}" not in md


# T09: 干净正文提取


def test_extract_main_density_beats_first_match():
    """第一个匹配容器嵌套大量导航链接时，密度打分应选出真正的正文容器。"""
    sidebar_links = "".join(f'<a href="/p{i}">link {i}</a>' for i in range(50))
    html = f"""
    <html><body>
      <div class="content">
        <nav>{sidebar_links}</nav>
        <article><p>{'正文内容。' * 40}</p></article>
      </div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    main = extract_main(soup)
    text = main.get_text()
    assert "正文内容" in text
    assert "link 49" not in text


def test_extract_main_removes_nav_inside_chosen_container():
    html = """
    <html><body>
      <article>
        <nav><a href="/a">a</a><a href="/b">b</a></nav>
        <p>正文保留。</p>
      </article>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    main = extract_main(soup)
    text = main.get_text()
    assert "正文保留" in text
    assert main.find("nav") is None


def test_extract_main_empty_container_falls_back_to_soup():
    """语义容器是空壳、正文直接在 body 下时，不误选空容器。"""
    html = """
    <html><body>
      <div class="content"></div>
      <p>真正的正文在容器之外。</p>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    main = extract_main(soup)
    assert "真正的正文在容器之外" in main.get_text()
