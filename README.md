# firecrawl-adapter

Firecrawl API 的本地免费替代。SearXNG 元搜索 + 协议适配，为 Claude Code (MCP) / Hermes 提供 `web_search`、`web_scrape`、`web_crawl`，无需付费 API key。**在 Claude Code 中运行**，服务管理用 `/devops`，Cookie 登录用 `/browser`，部署用 `/deploy`。

> GitHub: [shunchengGit/firecrawl-adapter](https://github.com/shunchengGit/firecrawl-adapter)

## 架构

```
Claude Code (MCP) / Hermes
  │  FIRECRAWL_API_URL=http://127.0.0.1:3672
  ▼
adapter :3672  实现 Firecrawl /v2/* 协议
  │
  ▼
SearXNG :3671 (Docker)  聚合 6 引擎，空时 Bing 兜底
  │
  ▼
Google / Bing / 360 / Wikipedia / Yandex / Presearch
```

## 快速开始

### 1. 安装

```
/devops setup
```

检查并安装 Docker、Python 3.10+、venv 依赖、Node.js + agent-browser、`.env`、cookie 共享。幂等，可重复运行。

### 2. 启动

```
/devops start
```

启动 SearXNG（Docker）+ adapter（本地）。`start` 缺依赖时会自动调 `setup`。

### 3. 验证

```bash
curl -X POST http://127.0.0.1:3672/v2/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Python", "limit": 5}'
```

### Cookie 登录

部分网站需登录后才能看到内容（如钉钉知识库）。要让 adapter 抓取到这些页面，只需手动登录一次：

1. 在 Claude Code 中执行 `/browser`，让它打开浏览器
2. 在浏览器中完成登录
3. 关闭浏览器（cookie 自动保存）

之后 adapter 的每次 headless 抓取都会自动加载这些 cookie，无需再次登录。

> 原理：`setup.sh` 在 `~/.zshrc` 中设置了 `AGENT_BROWSER_SESSION_NAME=firecrawl-adapter`，agent-browser 的每个 session 关闭时会把 cookie 存到共享文件，新 session 打开时自动加载，形成传递链。

## 运维

所有操作通过 Claude Code 的 `devops` 技能：

| 命令 | 作用 |
|------|------|
| `/devops setup` | 首次安装依赖 |
| `/devops start` | 启动 SearXNG + adapter |
| `/devops stop` | 停止全部服务 |
| `/devops reload` | 重载 adapter 代码 |
| `/devops status` | 查看服务状态 |
| `/devops logs` | 查看 adapter 日志 |
| `/devops check` | pytest + ruff + mypy |

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

**6 个引擎**（`searxng/settings.yml.template`，`start.sh` 根据 `.env` 生成）：

| 引擎 | 直连 | 说明 |
|------|------|------|
| 360搜索 | ✅ | 国内引擎，稳定 |
| Bing | ✅ | 国际，国内直连 |
| Google | ❌ 需代理 | 被墙 |
| Wikipedia | ❌ 需代理 | 被墙 |
| Yandex | ✅ | 中英文覆盖好 |
| Presearch | ✅ | 去中心化搜索 |

**代理**：`.env` 设 `SEARXNG_PROXY=http://host.docker.internal:7890` 解封 Google/Wikipedia。必须用 `host.docker.internal`（容器内 `127.0.0.1` 指向自身）。无代理时仅 bing/yandex/360 可用（~23 条）。

**兜底**：SearXNG 返回空时自动切 Bing HTML scrape（国内直连，中文友好）。

**已禁用**：百度/搜狗（CAPTCHA）、DuckDuckGo/Mojeek（不稳定）、Brave/Startpage/Qwant/Yahoo/Naver 等。

## 开发

```bash
pytest                          # 测试
ruff check adapter/ tests/      # lint
mypy adapter/                   # 类型检查
```
