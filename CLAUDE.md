# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

`firecrawl-adapter` 是本地 Firecrawl 协议适配器。客户端调用 `/v1/*` 或 `/v2/*` HTTP API；adapter 将搜索请求转给本地 SearXNG，并直接抓取网页。SearXNG 与 Valkey 在 Docker 中运行，adapter 通常作为宿主机 Python 进程运行，以便被反爬拦截时调用宿主机上的 `agent-browser`。

面向使用者的安装、Cookie 登录、API 示例及 Hermes / Claude Code MCP 部署说明见 `README.md`。服务生命周期操作优先使用项目的 `devops` skill 或其脚本。

## 常用命令

```bash
# 首次安装：检查 Docker/Python 3.10+，创建 .venv，安装开发依赖，配置 .env
./.claude/skills/devops/scripts/setup.sh

# 推荐的服务生命周期；start 会生成 SearXNG 配置、启动 Docker 服务并在本地运行 adapter
./.claude/skills/devops/scripts/start.sh
./.claude/skills/devops/scripts/reload.sh
./.claude/skills/devops/scripts/status.sh
./.claude/skills/devops/scripts/logs.sh [adapter|searxng|redis]
./.claude/skills/devops/scripts/stop.sh

# 一次运行 pytest + ruff + mypy
./.claude/skills/devops/scripts/check.sh

# 测试、单文件与单个测试
./.claude/skills/devops/scripts/test.sh
./.claude/skills/devops/scripts/test.sh tests/test_parser.py
./.claude/skills/devops/scripts/test.sh tests/test_parser.py::test_match_path_wildcard
python -m pytest -q
python -m pytest tests/test_parser.py::test_match_path_wildcard -v

# lint 与类型检查
./.claude/skills/devops/scripts/lint.sh
./.claude/skills/devops/scripts/lint.sh --fix
./.claude/skills/devops/scripts/typecheck.sh
python -m ruff check adapter/ tests/
python -m mypy adapter/

# 手动运行：compose 只启动 SearXNG 与 Valkey，不会启动 adapter
docker compose up -d
python -m adapter                 # 也可用 firecrawl-adapter

# 构建 wheel（Hatchling 后端）
python -m pip wheel .
```

项目要求 Python 3.10+。Ruff 目标版本为 3.10、行长 100；测试文件忽略 E501。Mypy 的检查范围是 `adapter/`。开发依赖可直接用 `python -m pip install -e ".[dev]"` 安装。

仓库的 Compose 配置没有 adapter service 或 `build` 段；`docker compose up -d --build` 不会从本仓库的 Dockerfile 构建并运行 adapter。

## 架构与修改边界

- **`adapter/server.py` 是 HTTP 边界。** 使用 `ThreadingHTTPServer`，负责请求体限制、JSON 解析、路由、HTTP 错误映射、健康检查和优雅关闭。端点业务逻辑应留在 handlers 中；这是唯一应接触 socket 的模块。
- **`adapter/handlers.py` 定义端点语义。** 每个 handler 接收解析后的 dict 并返回响应 dict，负责参数验证和 Firecrawl 兼容的响应形状，因此可以脱离 HTTP 层单测。
- **`adapter/fetcher.py` 集中所有网络 I/O。** 搜索会把域名过滤编译为 `site:` / `-site:`（仅上游提示），最终结果按解析后的 hostname 做 include/exclude 硬过滤（排除优先、子域名匹配）并规范化去重，过滤去重后才截取 limit；仅当 SearXNG 返回空结果时使用 Bing HTML scrape 兜底（同一编译 query）。抓取先尝试 `requests`，失败或疑似受阻时调用 `agent-browser`；两条路径都经 `classify_html` 有效性分类（`ScrapeResult.status`），失败不再返回 success 占位正文。headless 路径会注入 MutationObserver 等待正文就绪（DOM 静默 + 文本规模，短页逃逸窗口为 budget×0.5），`timeout`/`waitFor` 均为毫秒并折算成单调时钟总预算。PDF 按 Content-Type 与 `%PDF-` 签名分流给 pypdf。
- **`adapter/ranking.py` 是搜索质量纯逻辑层。** 实体提取（保留连字符术语与短产品名，短实体用词边界匹配）、官方/具体性意图识别、可解释打分重排、同站多样性限流与补搜变体生成；不发起网络请求，离线可测。
- **`adapter/parser.py` 是 HTML 纯辅助层。** `html_to_markdown` 必须为每份文档新建 `HTML2Text` 实例——该库会跨 `handle()` 保留文档级状态（缩写、脚注定义），同线程复用会串页。`extract_main` 用文本密度打分选择正文容器（而非第一个匹配），并在容器内移除导航类噪声。
- **`adapter/jobs.py` 管理进程内 crawl job。** Crawl 由有界 `ThreadPoolExecutor` 调度，状态按 `queued → scraping → completed|failed|cancelled|timeout` 转换；worker 按同 host 串行 BFS，并增量发布结果和进度。活跃及排队任务分别受配置限制，终态不可被覆盖，TTL/容量清理只删除终态任务。任务不持久化，adapter 重启后会消失；状态分页使用本地 `?page=N`。取消和超时是协作式的，正在执行的同步页面抓取可能先返回，但不得继续发布或调度。
- **`adapter/config.py` 在 import 时加载配置。** 它从项目根 `.env` 读取环境变量并创建冻结的全局 `config` 单例；修改 `.env` 后必须重启 adapter，运行中不会自动重载。

关键数据流：

```text
POST /search → server → handle_search → compile query → SearXNG → 空结果时 Bing fallback
             → 域名硬过滤 + 去重 → ranking 意图重排 → 质量不足时有限补搜一轮
             → 可选 scrapeOptions：有界抓取候选，失败换来源
POST /scrape → server → handle_scrape → scrape_url_result → requests → blocked 时 agent-browser
             → classify 有效性分类（ok/partial 才 success，否则带 code 失败）→ parser
POST /crawl → server → 校验并准入内存 job → 有界 dispatcher → scrape_url → BFS → 客户端轮询增量状态
```

## API 兼容约束

- `/v1` 与 `/v2` 都支持 search、scrape、crawl 和 map；extract 当前仅支持 `POST /v2/extract`。
- `/health` 与 `/healthz` 无论 SearXNG 是否可达都返回 HTTP 200；需检查 JSON 中的 `status: "ok" | "degraded"` 和 `searxng: "up" | "down"`。
- 扩展 handler 时保留现有响应形状。搜索响应包含 `data.web` 与本地生成的 `searchId`；crawl 状态中的 `next` 是带 `?page=N` 的相对 URL，不是真正 Firecrawl 的不透明 cursor。Crawl 状态还包含 `discovered`、`queued`、`completed`、`failed`、`skipped`；容量耗尽以 `code: "crawl_capacity_exhausted"` 表示。
- scrape 成功响应的 `metadata.scrapeStatus` 为 `ok` 或 `partial`（partial 附 `warning`）；失败返回 `success: false` 与 `code`（`page_not_found` / `access_restricted` / `content_incomplete` / `unsupported_format` / `fetch_failed` / `scrape_timeout`）。新增失败分类时同步更新 README 能力矩阵。
- `SEARXNG_DISABLED_ENGINES` 用于实测异常引擎的环境级隔离，只影响默认引擎集（`SEARXNG_ENGINES` 为空时基于 fetcher 内置的模板默认清单做减法）；它是临时措施，不是永久黑名单。

## SearXNG 与浏览器约束

- `searxng/settings.yml` 是 gitignored 生成物。`start.sh` 从 `searxng/settings.yml.template` 渲染，并替换 `SEARXNG_PROXY`；不要把生成文件当作配置源直接修改。
- 宿主机代理从 SearXNG 容器内应写为 `host.docker.internal`，不能使用容器内指向自身的 `127.0.0.1`。
- 抓取的 blocked-page 启发式有意把可见文本少于 500 字符或包含反机器人标记的页面判为疑似受阻；合法短页面也可能触发浏览器回退，不要在未评估反爬效果前移除该逻辑。
- 每次 headless fallback 使用独立的 `adapter_<id>` session，并只关闭自己创建的 session。adapter 优雅关闭时会取消运行中的 crawl，并调用 `agent-browser close --all` 使浏览器会话落盘。
- Dockerfile 中没有 `agent-browser`；需要浏览器回退时应保持 adapter 在宿主机运行，不要假定容器运行具有等价能力。

## 测试分层

正常测试套件应保持离线且确定性，不依赖正在运行的 SearXNG：

- `tests/test_parser.py`：parser 纯函数行为；
- `tests/test_handlers.py`：handler 验证、响应形状及 mock 后的上游交互；
- `tests/test_routing.py`：通过进程内 `ThreadingHTTPServer` 验证 HTTP 路由和错误映射；
- `tests/test_fetcher.py`：域名过滤/去重、有效性分类、PDF 解析与受控时钟下的 headless 等待（subprocess 全 mock）；
- `tests/test_ranking.py`：实体提取、意图识别、重排与补搜变体的纯逻辑行为。

真实效果验收使用显式联网脚本，不属于默认测试套件、不自动启停服务：`scripts/eval_baseline.py`（搜索 12 查询 + 抓取 12 页面基准，报告写入 `reports/`）与 `scripts/engine_probe.py`（SearXNG 单引擎对照诊断）。
