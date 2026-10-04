#!/usr/bin/env python3
"""SearXNG 单引擎诊断探针（T02）：逐引擎对照，识别异常引擎。

显式诊断工具，不属于默认测试套件，不经过 adapter：

    python scripts/engine_probe.py [--base http://127.0.0.1:3671] \
        [--engines bing,360search,yandex]

注意：同时传 categories 会让 SearXNG 扩展引擎集，单引擎探针不得携带
categories 参数。每个探针打印返回结果的实际来源引擎，供核实“指定引擎
是否真的被执行”。错误/验证码与“正常零结果”分开展示。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

DEFAULT_ENGINES = ["360search", "quark", "bing", "wikipedia", "fynd", "yandex", "presearch"]

PROBES = [
    ("zh", "杭州 西湖 景区 预约 官方"),
    ("en", "agent-browser session-name cookie persistence"),
]


def probe(base: str, engine: str, query: str) -> dict:
    params = urllib.parse.urlencode({"q": query, "format": "json", "engines": engine})
    req = urllib.request.Request(
        f"{base}/search?{params}", headers={"User-Agent": "engine-probe/1.0"}
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "seconds": time.monotonic() - started}
    results = data.get("results", [])
    actual_engines = sorted({e for item in results for e in item.get("engines", [])})
    return {
        "seconds": round(time.monotonic() - started, 2),
        "count": len(results),
        "actual_engines": actual_engines,
        "engine_mismatch": bool(actual_engines) and actual_engines != [engine],
        "unresponsive": data.get("unresponsive_engines", []),
        "top": [
            {"title": item.get("title", "")[:60], "url": item.get("url", "")[:90]}
            for item in results[:3]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SearXNG 单引擎诊断探针")
    parser.add_argument("--base", default="http://127.0.0.1:3671", help="SearXNG 地址")
    parser.add_argument("--engines", default=",".join(DEFAULT_ENGINES))
    args = parser.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    print(f"SearXNG: {args.base}；引擎: {', '.join(engines)}\n")

    for lang, query in PROBES:
        print(f"== [{lang}] {query} ==")
        for engine in engines:
            r = probe(args.base, engine, query)
            if "error" in r:
                print(f"  {engine:<12} 错误: {r['error'][:70]}")
                continue
            flags = []
            if r["engine_mismatch"]:
                flags.append(f"实际引擎={r['actual_engines']}")
            if r["unresponsive"]:
                flags.append(f"unresponsive={r['unresponsive']}")
            flag = " " + " ".join(flags) if flags else ""
            print(f"  {engine:<12} {r['count']:>2} 条 {r['seconds']:>5}s{flag}")
            for item in r["top"]:
                print(f"      - {item['title']} | {item['url']}")
        print()


if __name__ == "__main__":
    main()
