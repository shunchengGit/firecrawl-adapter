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
- **`adapter/fetcher.py` 集中所有网络 I/O。** 搜索会把域名过滤编译为 `site:` / `-site:`，将 Firecrawl source 类型映射为 SearXNG 分类，以两倍数量预取后过滤；仅当 SearXNG 返回空结果时使用 Bing HTML scrape 兜底。抓取先尝试 `requests`，失败或疑似受阻时调用 `agent-browser`。
- **`adapter/parser.py` 是 HTML 纯辅助层。** `HTML2Text` 实例必须保持线程局部，因为 HTTP handler 与 crawl worker 会并发运行。
- **`adapter/jobs.py` 管理进程内 crawl job。** `POST /crawl` 创建 daemon thread 后立即返回；worker 按同 host BFS 遍历，并受深度、路径过滤、页面数、队列大小及整体超时限制。任务不持久化，adapter 重启后会消失；状态分页使用本地 `?page=N`。
- **`adapter/config.py` 在 import 时加载配置。** 它从项目根 `.env` 读取环境变量并创建冻结的全局 `config` 单例；修改 `.env` 后必须重启 adapter，运行中不会自动重载。

关键数据流：

```text
POST /search → server → handle_search → compile query → SearXNG → 空结果时 Bing fallback
POST /scrape → server → handle_scrape（最多重试 3 次）→ requests → blocked 时 agent-browser → parser
POST /crawl → server → 创建内存 job + daemon worker → scrape_url → BFS → 客户端轮询状态
```

## API 兼容约束

- `/v1` 与 `/v2` 都支持 search、scrape、crawl 和 map；extract 当前仅支持 `POST /v2/extract`。
- `/health` 与 `/healthz` 无论 SearXNG 是否可达都返回 HTTP 200；需检查 JSON 中的 `status: "ok" | "degraded"` 和 `searxng: "up" | "down"`。
- 扩展 handler 时保留现有响应形状。搜索响应包含 `data.web` 与本地生成的 `searchId`；crawl 状态中的 `next` 是带 `?page=N` 的相对 URL，不是真正 Firecrawl 的不透明 cursor。

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
- `tests/test_routing.py`：通过进程内 `ThreadingHTTPServer` 验证 HTTP 路由和错误映射。
