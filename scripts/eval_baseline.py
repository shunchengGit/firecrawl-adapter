#!/usr/bin/env python3
"""功能效果基准评估（T01）：对运行中的 adapter 执行固定样本并生成报告。

显式联网验收工具，不属于默认离线测试套件：

    python scripts/eval_baseline.py [--base http://127.0.0.1:3672] [--out reports/]

报告包含自动检查（域名约束兑现、分类正确性、关键标记命中）与人工评分槽位。
人工评分口径：0=无关，1=主题相关但不直接满足问题，2=直接满足问题。
不记录代理凭据、Cookie 或敏感正文。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 基准样本：查询（12 条）
# expected_domains: 期望命中的官方/可信域名（人工评分参照，非硬约束）
# include_domains: 作为请求参数传入的硬约束（必须 100% 兑现）
# ---------------------------------------------------------------------------
QUERIES = [
    {"id": "q01", "query": "Python asyncio TaskGroup 官方文档",
     "expected_domains": ["docs.python.org"], "note": "官方具体 API 页"},
    {"id": "q02", "query": "FastAPI WebSocket disconnect handling documentation",
     "expected_domains": ["fastapi.tiangolo.com"], "note": "WebSockets 专题页"},
    {"id": "q03", "query": "中华人民共和国个人信息保护法 全文",
     "expected_domains": ["gov.cn"], "note": "法律全文或官方转载"},
    {"id": "q04", "query": "杭州 西湖 景区 预约 官方",
     "expected_domains": ["westlake.hangzhou.gov.cn", "hangzhou.gov.cn"], "note": "官方预约入口"},
    {"id": "q05", "query": "uv pip compile generate lockfile documentation",
     "expected_domains": ["docs.astral.sh"], "note": "uv compile 专题页"},
    {"id": "q06", "query": "agent-browser session-name cookie persistence",
     "expected_domains": ["agent-browser.dev", "github.com"], "note": "官方 sessions 文档"},
    {"id": "q07", "query": '"agent-browser" "session-name"',
     "expected_domains": ["agent-browser.dev", "github.com"], "note": "精确短语"},
    {"id": "q08", "query": "uv pip compile", "include_domains": ["docs.astral.sh"],
     "expected_domains": ["docs.astral.sh"], "note": "域名硬约束必须 100% 兑现"},
    {"id": "q09", "query": "Requests library timeout parameter documentation",
     "expected_domains": ["requests.readthedocs.io"], "note": "英文技术细节"},
    {"id": "q10", "query": "北京 社保 查询 官方入口",
     "expected_domains": ["beijing.gov.cn", "rsj.beijing.gov.cn"], "note": "政务服务官方入口"},
    {"id": "q11", "query": "docker compose depends_on condition service_healthy",
     "expected_domains": ["docs.docker.com"], "note": "长尾配置细节"},
    {"id": "q12", "query": "Python walrus operator examples",
     "expected_domains": ["docs.python.org", "peps.python.org"], "note": "歧义短词（海象）"},
]

# ---------------------------------------------------------------------------
# 基准样本：页面（12 个）
# expect: ok / not_found / restricted 之一；markers 为应出现的关键内容
# ---------------------------------------------------------------------------
PAGES = [
    {"id": "p01", "url": "https://docs.python.org/3/library/asyncio-task.html",
     "expect": "ok", "markers": ["TaskGroup", "create_task"], "note": "静态技术文档"},
    {"id": "p02", "url": "https://www.ruanyifeng.com/blog/2016/04/cors.html",
     "expect": "ok", "markers": ["CORS", "跨域"], "note": "中文长文"},
    {"id": "p03", "url": "https://fastapi.tiangolo.com/advanced/websockets/",
     "expect": "ok", "markers": ["WebSocketDisconnect"], "note": "导航密集文档",
     "only_main": True, "noise_markers": []},
    {"id": "p04", "url": "https://quotes.toscrape.com/js/",
     "expect": "ok", "markers": ["The world as we have created"], "note": "普通 JS"},
    {"id": "p05", "url": "https://quotes.toscrape.com/js-delayed/",
     "expect": "ok", "markers": ["The world as we have created"], "note": "延迟 10 秒 JS"},
    {"id": "p06", "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
     "expect": "ok", "markers": ["Dummy PDF file"], "note": "文本型 PDF"},
    {"id": "p07", "url": "https://www.sjz.gov.cn/gfdyzfxxgk/columns/ad870ff7-4413-4608-a083-0ba48a93d88a/202503/03/e7eb03a7-bca3-4cb2-9ae1-c14018360a6a.html",
     "expect": "ok", "markers": ["第七十四条"], "note": "政府法律转载长文（可能漂移）"},
    {"id": "p08", "url": "https://www.gov.cn/xinwen/2021-08/20/content_5632486.htm",
     "expect": "not_found", "markers": [], "note": "失效页应分类 not_found"},
    {"id": "p09", "url": "https://zhuanlan.zhihu.com/p/1999160608529072176",
     "expect": "restricted", "markers": [], "note": "匿名受限页应分类 restricted"},
    {"id": "p10", "url": "https://example.com/",
     "expect": "ok", "markers": ["documentation examples"], "note": "合法短页面不应误拒"},
    {"id": "p11", "url": "https://quotes.toscrape.com/",
     "expect": "ok", "markers": ["Quotes to Scrape"], "note": "普通静态页"},
    {"id": "p12", "url": "https://docs.python.org/3/tutorial/introduction.html",
     "expect": "ok", "markers": ["Python"], "note": "代码块保留检查"},
]


def _post(base: str, path: str, payload: dict, timeout: float = 180) -> dict:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower()


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def run_queries(base: str) -> list[dict]:
    rows = []
    for q in QUERIES:
        payload: dict = {"query": q["query"], "limit": 5}
        if q.get("include_domains"):
            payload["includeDomains"] = q["include_domains"]
        started = time.monotonic()
        try:
            res = _post(base, "/v2/search", payload)
            results = res.get("data", {}).get("web", [])
        except Exception as e:
            rows.append({**q, "error": str(e), "results": []})
            continue
        elapsed = time.monotonic() - started

        hosts = [_host(r.get("url", "")) for r in results]
        # 域名硬约束兑现检查
        constraint_ok = True
        if q.get("include_domains"):
            constraint_ok = all(
                any(_host_matches(h, d) for d in q["include_domains"]) for h in hosts
            )
        # 期望域名首次出现名次（0 = 未命中）
        first_expected = 0
        for i, h in enumerate(hosts, start=1):
            if any(_host_matches(h, d) for d in q["expected_domains"]):
                first_expected = i
                break
        rows.append({
            **q,
            "seconds": round(elapsed, 2),
            "results": [
                {"title": r.get("title", "")[:80], "url": r.get("url", "")} for r in results
            ],
            "constraint_ok": constraint_ok,
            "first_expected_rank": first_expected,
        })
    return rows


def run_pages(base: str) -> list[dict]:
    rows = []
    for p in PAGES:
        payload: dict = {
            "url": p["url"],
            "formats": ["markdown"],
            "timeout": 45000,
        }
        if p.get("only_main"):
            payload["onlyMainContent"] = True
        started = time.monotonic()
        try:
            res = _post(base, "/v2/scrape", payload)
        except Exception as e:
            rows.append({**p, "error": str(e)})
            continue
        elapsed = time.monotonic() - started

        doc = res.get("data") or {}
        markdown = doc.get("markdown", "") or ""
        status = (doc.get("metadata") or {}).get("scrapeStatus", "")
        code = res.get("code", "")
        success = res.get("success", False)
        marker_hits = [m for m in p["markers"] if m in markdown]

        # 分类判定：成功页取 metadata.scrapeStatus；失败页取错误码映射
        if success:
            actual = status or "ok"
        else:
            actual = {
                "page_not_found": "not_found",
                "access_restricted": "restricted",
            }.get(code, code or "unknown")

        rows.append({
            **p,
            "seconds": round(elapsed, 2),
            "success": success,
            "actual": actual,
            "classification_ok": actual == p["expect"],
            "markdown_chars": len(markdown),
            "marker_hits": marker_hits,
            "markers_ok": len(marker_hits) == len(p["markers"]),
            "warning": res.get("warning", ""),
        })
    return rows


def render_report(base: str, query_rows: list[dict], page_rows: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# 功能效果基准报告",
        "",
        f"- 时间：{now}",
        f"- adapter：{base}",
        "- 评分口径：0=无关，1=主题相关但不直接满足，2=直接满足（人工填写）",
        "- Hit@5：前五条至少一条评分 2；本报告的自动检查不能替代人工评分",
        "",
        "## 搜索样本",
        "",
        "| ID | 查询 | 耗时s | 约束兑现 | 期望域名名次 | 人工Hit@5 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in query_rows:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['query'][:30]} | - | - | 错误: {r['error'][:30]} | | |")
            continue
        lines.append(
            f"| {r['id']} | {r['query'][:30]} | {r['seconds']} | "
            f"{'✓' if r['constraint_ok'] else '✗'} | "
            f"{r['first_expected_rank'] or '未命中'} | | {r['note']} |"
        )
    lines += ["", "### 搜索明细（前五条）", ""]
    for r in query_rows:
        lines.append(f"**{r['id']} {r['query']}**")
        if "error" in r:
            lines.append(f"- 请求失败：{r['error']}")
        for i, item in enumerate(r.get("results", []), start=1):
            lines.append(f"{i}. [{item['title']}]({item['url']}) — 人工评分：")
        lines.append("")

    lines += [
        "## 抓取样本",
        "",
        "| ID | 页面 | 期望分类 | 实际分类 | 分类正确 | 关键标记 | 正文字符 | 耗时s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in page_rows:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['note']} | {r['expect']} | 错误 | ✗ | - | - | - |")
            continue
        missing = len(r["markers"]) - len(r["marker_hits"])
        marker_cell = "✓" if r["markers_ok"] else f"缺 {missing}"
        lines.append(
            f"| {r['id']} | {r['note']} | {r['expect']} | {r['actual']} | "
            f"{'✓' if r['classification_ok'] else '✗'} | "
            f"{marker_cell} | "
            f"{r['markdown_chars']} | {r['seconds']} |"
        )

    q_ok = sum(1 for r in query_rows if r.get("constraint_ok") and r.get("first_expected_rank"))
    p_cls = sum(1 for r in page_rows if r.get("classification_ok"))
    p_mark = sum(
        1 for r in page_rows if r["expect"] == "ok" and r.get("markers_ok")
    )
    p_ok_total = sum(1 for r in page_rows if r["expect"] == "ok")
    lines += [
        "",
        "## 汇总（自动检查，非最终质量结论）",
        "",
        f"- 域名约束兑现且命中期望域名：{q_ok}/{len(query_rows)}",
        f"- 抓取分类正确：{p_cls}/{len(page_rows)}",
        f"- 公开可读样本取得关键正文：{p_mark}/{p_ok_total}",
        "- 人工评分待填：搜索 Hit@5、无关结果数、抓取正文质量",
        "- 未测项须在任务记录中明确标注",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="firecrawl-adapter 功能效果基准评估")
    parser.add_argument("--base", default="http://127.0.0.1:3672", help="adapter 地址")
    parser.add_argument("--out", default="reports", help="报告输出目录")
    args = parser.parse_args()

    print(f"搜索样本评估（{len(QUERIES)} 条）...")
    query_rows = run_queries(args.base)
    print(f"抓取样本评估（{len(PAGES)} 个，动态页较慢）...")
    page_rows = run_pages(args.base)

    report = render_report(args.base, query_rows, page_rows)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"报告已写入 {out_path}")
    print()
    # 终端简报
    for r in page_rows:
        if "error" in r:
            print(f"  {r['id']} 错误: {r['error'][:60]}")
        else:
            flag = "✓" if r["classification_ok"] and r["markers_ok"] else "✗"
            print(
                f"  {flag} {r['id']} {r['note']}：期望 {r['expect']}，实际 {r['actual']}，"
                f"标记 {len(r['marker_hits'])}/{len(r['markers'])}"
            )


if __name__ == "__main__":
    main()
