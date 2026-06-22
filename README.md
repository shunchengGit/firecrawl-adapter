# firecrawl-adapter

Firecrawl API 的本地免费替代品。通过 SearXNG 元搜索引擎 + 协议适配器，为 Hermes / Claude Code (MCP) 提供 `web_search`、`web_scrape`、`web_crawl` 等能力，无需付费 API key。**必须在 Claude Code 中通过 `devops` 技能操作。**

> GitHub: [shunchengGit/firecrawl-adapter](https://github.com/shunchengGit/firecrawl-adapter)

## 架构

```
Hermes / Claude Code (MCP)
  │  FIRECRAWL_API_URL=http://127.0.0.1:3672
  ▼
adapter（端口 3672）— /v2/search, /v2/scrape, /v2/crawl ...
  │
  ▼
SearXNG（Docker，端口 3671）— 聚合 6 引擎，空时 Bing 兜底
  │
  ▼
Google / Bing / 360 / Wikipedia / Yandex / Presearch
```

## 目录结构

| 路径 | 说明 |
|------|------|
| `docker-compose.yml` | SearXNG + Valkey(Redis) 容器编排 |
| `Dockerfile` | 适配器镜像（可选，全 Docker 部署用） |
| `adapter/` | 适配器 Python 包 |
| `searxng/settings.yml` | SearXNG 配置（引擎、端口） |
| `searxng/limiter.toml` | 速率限制 |
| `tests/` | 单元测试与集成测试 |
| `pyproject.toml` | 项目元数据、依赖、ruff/mypy 配置 |

## 快速启动

> **必须通过 Claude Code 操作**，在 Claude Code 会话中使用 `devops` 技能管理服务：
> ```
> /devops setup    # 首次安装依赖（Docker/Python/venv/agent-browser/.env）
> /devops start    # 启动 SearXNG + adapter
> /devops stop     # 停止全部服务
> /devops reload   # 重载 adapter 代码
> /devops status   # 查看服务状态
> /devops logs     # 查看 adapter 日志
> /devops check    # pytest + ruff + mypy
> ```

SearXNG 用 Docker 最省心；adapter 本地跑最灵活（agent-browser 兜底可用）。

也可直接调脚本：

```bash
./.claude/skills/devops/scripts/setup.sh   # 首次安装依赖
./.claude/skills/devops/scripts/start.sh   # 启动服务
```

手动操作（不推荐）：

```bash
docker compose up -d                # 1. 启动 SearXNG + Redis
pip install -e ".[dev]"             # 2. 安装 Python 依赖（首次）
python -m adapter                   # 3. 启动 adapter
```

- SearXNG: `http://127.0.0.1:3671`
- adapter: `http://127.0.0.1:3672`

可选依赖（反爬页面需要）：

```bash
npm i -g agent-browser && agent-browser install
```

## 验证

```bash
# 基本搜索
curl -X POST http://127.0.0.1:3672/v2/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Python", "limit": 5}'

# 中文搜索 + 域名过滤
curl -X POST http://127.0.0.1:3672/v2/search \
  -H "Content-Type: application/json" \
  -d '{"query":"Python 教程","limit":10,"language":"zh-CN","includeDomains":["runoob.com"]}'
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/healthz` | 健康检查（含 SearXNG 存活探测） |
| POST | `/v2/search` | 网页搜索（分页 + query 编译 + Bing 兜底） |
| POST | `/v2/scrape` | 抓取单页（requests → agent-browser 兜底） |
| POST | `/v2/crawl` | 爬取网站（异步 BFS） |
| GET | `/v2/crawl/:id` | 查询爬取状态（`?page=N` 分页） |
| DELETE | `/v2/crawl/:id` | 取消爬取 |
| POST | `/v2/extract` | 批量抓取（最多 5 URL） |
| POST | `/v2/map` | 获取站点链接列表 |

## 配置

在 `.env` 中设置（从 `.env.example` 复制）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SEARXNG_BASE` | `http://127.0.0.1:3671` | SearXNG 地址 |
| `ADAPTER_HOST` | `127.0.0.1` | adapter 监听地址 |
| `ADAPTER_PORT` | `3672` | adapter 监听端口 |
| `ADAPTER_MAX_SEARCH_RESULTS` | `20` | 单次搜索最大条数 |
| `ADAPTER_MAX_SCRAPE` | `60000` | 单页抓取最大字符数 |
| `ADAPTER_CRAWL_TIMEOUT` | `300` | 单次爬取超时（秒） |
| `ADAPTER_MAX_JOBS` | `100` | 最大保留任务数 |
| `ADAPTER_JOB_TTL` | `3600` | 任务保留时长（秒） |
| `ADAPTER_MAX_BODY_BYTES` | `2097152` | 请求体最大字节数 |
| `SEARXNG_PROXY` | `http://host.docker.internal:7890` | SearXNG 代理（留空=无代理） |

## 搜索引擎

当前 **6 个引擎**（`searxng/settings.yml.template`）：

| 引擎 | 直连 | 说明 |
|------|------|------|
| 360搜索 | ✅ | 国内引擎，稳定 |
| Bing | ✅ | 国际，国内直连 |
| Google | ❌ 需代理 | 被墙 |
| Wikipedia | ❌ 需代理 | 被墙 |
| Yandex | ✅ | 中英文覆盖好 |
| Presearch | ✅ | 去中心化搜索 |

### 代理

在 `.env` 中设 `SEARXNG_PROXY`，`start.sh` 会自动注入 `searxng/settings.yml`：

```bash
SEARXNG_PROXY=http://host.docker.internal:7890   # 启用（解封 Google/Wikipedia）
# SEARXNG_PROXY=                                   # 留空=无代理
```

- 必须用 `host.docker.internal`（`127.0.0.1` 在容器内指向自身）
- 无代理时仅 bing/yandex/360 可用（~23 条），Google/Wikipedia 需设 `disabled: true`

### 兜底

SearXNG 返回空时自动切 **Bing HTML scrape**（国内直连，中文友好）。

### 已禁用

百度/搜狗（持续 CAPTCHA）、DuckDuckGo/Mojeek（不稳定超时）、Brave/Startpage/Qwant/Wikidata/Yahoo/AOL/Seznam/Naver（不可用或覆盖差）。

## 开发

```bash
pytest                          # 测试
ruff check adapter/ tests/      # lint
mypy adapter/                   # 类型检查
```
