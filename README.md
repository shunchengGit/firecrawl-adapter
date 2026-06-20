# firecrawl-adapter

Firecrawl API 的本地免费替代品。通过 SearXNG 元搜索引擎 + 协议适配器，为 Hermes / Claude Code (MCP) 提供 `web_search`、`web_scrape`、`web_crawl` 等能力，无需付费 API key。

> GitHub: [shunchengGit/firecrawl-adapter](https://github.com/shunchengGit/firecrawl-adapter)

## 架构

```
Hermes (web_tools.py)          Claude Code (MCP)
  │  FIRECRAWL_API_URL=...       │  npx firecrawl-mcp
  ▼                              ▼
  └────────────┬─────────────────┘
               ▼
Firecrawl 适配器 (adapter/)   端口 3672
  │  实现 /v2/search, /v2/scrape, /v2/crawl 等 Firecrawl 协议
  ▼
SearXNG 元搜索引擎 (Docker)   端口 3671
  │  聚合多个搜索引擎
  ▼
┌──────────┬────────┬──────┬───────────┐
│  Google  │  Bing  │ Baidu│ DuckDuckGo│  ...
└──────────┴────────┴──────┴───────────┘
```

## 目录结构

| 路径 | 说明 |
|------|------|
| `docker-compose.yml` | SearXNG + Valkey(Redis) 容器编排 |
| `Dockerfile` | 适配器镜像构建（可选，用于全 Docker 部署） |
| `adapter/` | 适配器 Python 包（server / handlers / fetcher / parser / jobs / config） |
| `searxng/settings.yml` | SearXNG 配置（引擎、端口等） |
| `searxng/limiter.toml` | 速率限制配置 |
| `tests/` | 单元测试与路由集成测试 |
| `pyproject.toml` | 项目元数据、依赖、ruff/mypy 配置 |

## 快速启动

### 方式 A：SearXNG（Docker）+ adapter（本地）推荐

SearXNG 依赖多、配置繁，用 Docker 最省心；adapter 是纯 Python，本地跑最灵活（agent-browser 兜底也能直接用本地的）。

```bash
# 一键安装依赖 + 启动服务
./.claude/skills/devops/scripts/setup.sh
./.claude/skills/devops/scripts/start.sh
```

或手动操作：

```bash
# 1. 启动 SearXNG + Redis
docker compose up -d

# 2. 安装 Python 依赖（首次）
pip install -e ".[dev]"

# 3. 启动 adapter
python -m adapter
```

- SearXNG: `http://127.0.0.1:3671`
- adapter: `http://127.0.0.1:3672`

### 方式 B：全部 Docker

```bash
docker compose up -d --build
```

注意：Docker 镜像内不含 agent-browser（headless 兜底不可用），需要反爬页面抓取请用方式 A。

### 验证

```bash
curl -X POST http://127.0.0.1:3672/v2/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "limit": 2}'
```

返回 JSON 搜索结果即表示正常。

## 适配器 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/healthz` | 健康检查 |
| POST | `/v2/search` | 网页搜索 |
| POST | `/v2/scrape` | 抓取单页内容（支持 agent-browser headless 兜底） |
| POST | `/v2/crawl` | 爬取网站（异步，返回 job ID） |
| GET | `/v2/crawl/:id` | 查询爬取状态及结果（支持 `?page=N` 分页） |
| DELETE | `/v2/crawl/:id` | 取消爬取任务 |
| POST | `/v2/map` | 获取站点链接列表 |

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SEARXNG_BASE` | `http://127.0.0.1:3671` | SearXNG 地址 |
| `ADAPTER_HOST` | `127.0.0.1` | 适配器监听地址 |
| `ADAPTER_PORT` | `3672` | 适配器监听端口 |
| `ADAPTER_MAX_JOBS` | `100` | 最大保留任务数 |
| `ADAPTER_JOB_TTL` | `3600` | 任务保留时长（秒） |
| `ADAPTER_MAX_BODY_BYTES` | `2097152` | 请求体最大字节数 |

## 开发

```bash
# 运行测试
pytest

# 代码检查
ruff check adapter/ tests/

# 类型检查
mypy adapter/
```

## 依赖

Python 包（见 `pyproject.toml`）：

- `requests` — HTTP 请求
- `beautifulsoup4` — HTML 解析
- `html2text` — HTML → Markdown 转换
- `lxml` — 解析后端

可选：[agent-browser](https://www.npmjs.com/package/agent-browser)（用于反爬页面的 headless 兜底抓取）。安装：`npm i -g agent-browser && agent-browser install`

## 搜索引擎

当前配置（`searxng/settings.yml`）启用了以下引擎：

- Google
- Bing
- DuckDuckGo
- Wikipedia
- Wikidata
- 百度
- 搜狗
