# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

Firecrawl API 的本地免费替代品。外部 agent（Hermes）把 `FIRECRAWL_API_URL` 指向本适配器；适配器把 Firecrawl 的 `/v2/*` 协议翻译成 SearXNG 搜索 + 直接抓取页面。无需付费 API key。Claude Code 也可以通过 MCP server 走本地搜索。

```
Hermes / Claude Code (MCP) → adapter (端口 3672) → SearXNG (端口 3671) → Google/Bing/Baidu/...
                                                    ↘ SearXNG 空时 → DuckDuckGo Lite (兜底)
```

## 常用命令

```bash
# 运维（devops skill 封装，推荐）
./.claude/skills/devops/scripts/start.sh        # 启动 SearXNG + adapter
./.claude/skills/devops/scripts/stop.sh         # 停止全部服务
./.claude/skills/devops/scripts/restart.sh      # 重启 adapter
./.claude/skills/devops/scripts/status.sh       # 查看服务状态
./.claude/skills/devops/scripts/logs.sh         # 查看 adapter 日志
./.claude/skills/devops/scripts/check.sh        # pytest + ruff + mypy 一次性检查

# 手动运行 adapter（需先启动 SearXNG）
docker compose up -d            # 只启动 SearXNG + Redis
python -m adapter               # 在 :3672 启动 adapter

# 测试 / lint / 类型检查
pytest                          # 全部测试
pytest tests/test_parser.py::test_match_path_wildcard   # 单个测试
ruff check adapter/ tests/      # lint（自动修复加 --fix）
mypy adapter/                   # 类型检查（必须 0 错误）

# 重新构建 Docker adapter 镜像（可选，全 Docker 模式）
docker compose up -d --build

# Claude Code MCP（firecrawl-local，已配在 user scope）
claude mcp list                 # 查看状态
claude mcp get firecrawl-local  # 详情
```

系统 Python 是 3.9，但 `pyproject.toml` 目标 3.10+。包内用了 `from __future__ import annotations`，所以 3.9 也能 import，但开发工具（ruff/mypy）按 3.10+ 处理。开发依赖安装：`pip install -e ".[dev]"`。

## 配置

所有端口和地址通过项目根的 `.env` 管理（已 gitignore，从 `.env.example` 复制）。`docker compose` 自动读 `.env`；`python -m adapter` 通过 `python-dotenv`（在 `adapter/config.py` 启动时加载）读 `.env`。

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `SEARXNG_PORT` | `3671` | SearXNG 主机端口（容器内固定 8080） |
| `ADAPTER_HOST` | `127.0.0.1` | adapter 监听地址 |
| `ADAPTER_PORT` | `3672` | adapter 监听端口 |
| `SEARXNG_BASE` | `http://127.0.0.1:3671` | adapter 指向 SearXNG 的地址 |
| `FIRECRAWL_API_URL` | `http://127.0.0.1:3672` | Hermes / MCP 指向 adapter 的地址 |
| `ADAPTER_MAX_SEARCH_RESULTS` | `20` | 单次搜索最大返回条数（>20 触发分页） |
| `SEARXNG_ENGINES` | `""` | 覆盖 SearXNG 搜索引擎（逗号分隔） |
| `SEARXNG_CATEGORIES` | `"general"` | 默认搜索分类 |

## 架构

`adapter/` 包按职责拆分——HTTP 层很薄，业务逻辑放在返回 dict 的纯函数里：

- **`server.py`** — `ThreadingHTTPServer` + `BaseHTTPRequestHandler` 子类。只做路由 + JSON 读写 + 错误包装。每个端点都委托给 `handlers.*` 的函数。这是唯一接触 socket 的地方。
- **`handlers.py`** — 每个端点一个函数（`handle_search`、`handle_scrape`、`handle_start_crawl`、`handle_crawl_status`、`handle_cancel_crawl`、`handle_extract`、`handle_map`）。每个接收解析后的 `body` dict，返回响应 dict。不感知 HTTP——这正是它们可单元测试的原因。
- **`fetcher.py`** — 所有网络 I/O。`scrape_url()` 先用 `requests.get`；如果页面看起来被反爬挡住（启发式：可见文本 <500 字符，或含 WAF 关键词），回退到 `scrape_url_headless()`，它会 shell out 调 `agent-browser`。另有 `searxng_search()`（多页分页 + 引擎/分类/语言过滤）、`ddg_search()`（DuckDuckGo Lite 兜底）、`compile_search_query()`（query 编译，domain → site: / -site: 操作符）和 `map_url()`。
- **`jobs.py`** — 内存中的爬取任务存储（`_jobs` dict + 锁）。`crawl_worker()` 在 daemon 线程里运行，按 BFS 遍历同域链接，最多到 `max_depth`。`cleanup_old_jobs()` 强制 TTL + 最大数量限制——每次新建任务时调用，防止内存无限增长。
- **`parser.py`** — 纯 HTML 辅助函数：`extract_main()`、`get_meta()`、`match_path()`、`html_to_markdown()`。线程局部的 `HTML2Text` 实例（该库非线程安全）。
- **`config.py`** — 冻结的 `Config` dataclass，所有值来自环境变量带默认值。全局唯一的 `config` 实例被各处 import。

**`/v2/scrape` 的关键流程：** `server.do_POST` → `handlers.handle_scrape`（重试 3 次）→ `fetcher.scrape_url` → requests.get → 失败时 → `scrape_url_headless`（子进程调 `agent-browser`）→ `parser` 构建 markdown/metadata/links。

**Crawl 是异步的：** `POST /v2/crawl` 立即返回 job_id，spawn `_crawl_worker` 线程，客户端轮询 `GET /v2/crawl/:id`。分页用虚拟的 `?page=N` 查询参数（真正的 Firecrawl 用不透明的 `next` URL——这里做了简化）。

## 踩过的坑 / 非显而易见的事

- **agent-browser 每次抓取后 close 自己的 session** — `scrape_url_headless` 随机生成 `adapter_<8hex>` session 名，finally 里只 close 自己，不杀其他 daemon（Hermes）。session 名随机化避免残留 daemon 冲突。
- **agent-browser cookie 共享**：`AGENT_BROWSER_SESSION_NAME=firecrawl-adapter`（`~/.zshrc`，`_env.sh` 默认值）使 agent-browser 原生支持跨 session cookie 互通——`close` 时自动保存到 `firecrawl-adapter-<session>.json`，新 session `open` 时自动从最新文件加载。不同 `--session` 各自独立 daemon，无并发冲突。不需共享 Chrome profile，不需 wrapper。
- **`/healthz` 探测 SearXNG** — 返回 `{"status":"ok"|"degraded","searxng":"up"|"down"}`，不只是 adapter 自身存活。SearXNG 不可达时 status 为 degraded。
- **crawl 有整体超时** — `ADAPTER_CRAWL_TIMEOUT`（默认 300s）控制单次 crawl 最长运行时间，超时 job 状态变 `timeout`（非 `completed`）。
- **优雅关闭** — adapter 捕获 SIGTERM/SIGINT，标记运行中 crawl 为 cancelled、关 agent-browser daemon 落盘 cookie、再 shutdown。`server.shutdown()` 在新线程调用避免与 `serve_forever` 死锁。
- **Docker 镜像里没有 agent-browser** — Dockerfile 只有 Python。headless 兜底只在本地运行模式下可用。不要尝试往镜像里加 agent-browser；构建时 Chromium 安装 + Chrome-for-Testing 下载会因网络限制失败。
- **`_is_likely_blocked` 阈值（500 字符）** 会对合法的短页面误判（如 `example.com`）。这是为了抓 Cloudflare 挑战页有意为之，但内容极少的页面会有误报。
- **SearXNG 配置以只读方式挂载** 通过 `docker-compose.yml` —— 本地编辑 `searxng/settings.yml`，重启容器生效。
- **SearXNG 引擎选择** — 默认加载 243 个引擎会导致超时风暴（`ResultContainer` 过早关闭，正常结果也被丢弃）。当前只启用 6 个：baidu/sogou（weight=2 优先）+ bing/google/duckduckgo/wikipedia（weight=1）。被墙引擎通过代理后可启用（见下）。
- **SearXNG 代理** — 通过 `outgoing.proxies` 配置全局代理。容器内必须用 `host.docker.internal`（`127.0.0.1` 指向容器自身）。当前代理 `host.docker.internal:7890`（macOS 系统代理端口）。
- **搜索三层增强**（借鉴 [firecrawl](https://github.com/mendable/firecrawl) 的 `search-query-builder.ts` + `search/v2/index.ts`）：
  1. **Query 编译** — `compile_search_query()` 把 `includeDomains`/`excludeDomains` 编译为 `site:` / `-site:` 操作符注入 query，上游引擎原生过滤
  2. **Limit×2 缓冲** — `fetch_limit = min(limit×2, max_search_results×2)`，多取一倍防过滤/去重损失
  3. **DDG 兜底** — SearXNG 返回空时自动切 DuckDuckGo Lite（纯 HTML 解析，无额外依赖）
- **SearXNG 搜索分页** — `searxng_search()` 当 `limit > 20`（SearXNG 每页默认 20 条）时自动循环获取多页。代理启用后 page 2/3 有真实数据（6 引擎 vs 之前 3 引擎只有 1 页）。支持 `engines`、`categories`、`language` 参数。`handle_search` 接受 `sources: [{type: "web"|"news"|"images"}]` 映射到 SearXNG 分类，响应含 `searchId`（uuid4 hex）供后续反馈。

## SearXNG

在 Docker 里跑（`docker compose up -d`）。配置在 `searxng/settings.yml`。

**引擎（6 个）**：baidu(weight=2) sogou(weight=2) bing google duckduckgo wikipedia。百度/搜狗优先（weight 越大越优先），google/ddg 通过代理访问（国内直连被墙）。

`secret_key` 硬编码为 `"hermes-searxng-local"` —— 仅本地用可以，但不要对外暴露。主机端口由 `SEARXNG_PORT` 控制（默认 3671）→ 容器内 8080。

## Claude Code MCP 集成

本适配器已作为 MCP server `firecrawl-local` 注册到 Claude Code 的 user scope（全局，所有项目可用），配置在 `~/.claude.json`：

- 命令：`npx -y firecrawl-mcp`
- 环境变量：`FIRECRAWL_API_URL=http://127.0.0.1:3672`、`FIRECRAWL_API_KEY=local`（占位，本地不校验）
- 暴露工具：`firecrawl_search`、`firecrawl_scrape` 等，走本地 adapter

**前置条件**：使用前必须确保 SearXNG + adapter 在跑，否则 MCP 工具会失败。

**内置 WebSearch 已禁用**：`~/.claude/settings.json` 的 `permissions.deny` 含 `"WebSearch"`，强制模型走 MCP 工具。恢复内置搜索则删掉该字段。

**Claude Code 内置 WebSearch 走的是 Anthropic API 后端**，无法直接指向本地 Firecrawl 端点（没有 `FIRECRAWL_API_URL` 之类的配置项，`ANTHROPIC_BASE_URL` 也只影响模型推理流量）。MCP 是唯一让 Claude Code 走本地搜索的方式。

**添加/移除 MCP**：
```bash
claude mcp add firecrawl-local -s user \
  -e FIRECRAWL_API_URL=http://127.0.0.1:3672 \
  -e FIRECRAWL_API_KEY=local \
  -- npx -y firecrawl-mcp
claude mcp remove firecrawl-local -s user
```
