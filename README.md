# firecrawl-adapter

Firecrawl API 的本地免费替代。SearXNG 元搜索 + 协议适配，为 Claude Code (MCP) / Hermes 提供 `web_search`、`web_scrape`、`web_crawl`，无需付费 API key。**在 Claude Code 中运行**，服务管理用 `/devops`，Cookie 登录用 `/browser`，部署用 `/deploy`。

> GitHub: [shunchengGit/firecrawl-adapter](https://github.com/shunchengGit/firecrawl-adapter)

## 1. 架构

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

## 2. 快速开始

### 2.1. 安装

```
/devops setup
```

检查并安装 Docker、Python 3.10+、venv 依赖、Node.js + agent-browser、`.env`、cookie 共享。幂等，可重复运行。

### 2.2. 启动

```
/devops start
```

启动 SearXNG（Docker）+ adapter（本地）。缺依赖时自动调 `setup`。

### 2.3. 验证

```bash
curl -X POST http://127.0.0.1:3672/v2/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Python", "limit": 5}'
```

## 3. 运维命令

| 命令 | 作用 |
|------|------|
| `/devops setup` | 首次安装依赖 |
| `/devops start` | 启动 SearXNG + adapter |
| `/devops stop` | 停止全部服务 |
| `/devops reload` | 重载 adapter 代码 |
| `/devops status` | 查看服务状态 |
| `/devops logs` | 查看 adapter 日志 |
| `/devops check` | pytest + ruff + mypy |

## 4. Cookie 登录

部分网站需登录后才能看到内容（如钉钉知识库）。要让 adapter 抓取到这些页面，只需手动登录一次：

1. 在 Claude Code 中执行 `/browser`，让它打开浏览器
2. 在浏览器中完成登录
3. 关闭浏览器（cookie 自动保存）

之后 adapter 的每次 headless 抓取都会自动加载这些 cookie，无需再次登录。

> 原理：`setup.sh` 在 `~/.zshrc` 中设置了 `AGENT_BROWSER_SESSION_NAME=firecrawl-adapter`，agent-browser 的每个 session 关闭时会把 cookie 存到共享文件，新 session 打开时自动加载，形成传递链。

## 5. API 端点

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

Crawl 任务保存在 adapter 进程内，重启后不会恢复。提交后任务先处于 `queued`，取得执行槽后转为 `scraping`，最终进入 `completed`、`failed`、`cancelled` 或 `timeout`；活跃与排队数量都有上限，容量用尽时返回 `code: "crawl_capacity_exhausted"`。状态响应会增量返回已成功页面，并包含 `discovered`、`queued`、`completed`、`failed`、`skipped` 计数。取消和超时是协作式的：正在执行的同步单页抓取可能需要先返回，但之后不会继续抓取或发现页面。

### 5.1. 搜索质量行为

`/v2/search` 的完整链路：query 编译（`site:`/`-site:`）→ SearXNG → 空结果时 Bing 兜底（同一编译 query）→ **域名硬过滤 + URL 校验 + 去重** → **按意图重排** → 质量不足时**有限补搜一次** → 截取 limit。

- `includeDomains` / `excludeDomains` 是本地硬约束（排除优先，子域名匹配），不只是上游提示；全部被过滤时返回真实剩余结果，不用无关结果凑数。
- 重排基于 title/url/snippet 中完整实体的命中、“官方/文档/全文”意图与页面具体性，同站结果限流保持多样性。
- 补搜只对高辨识度实体生成保守变体（精确短语），最多一轮；不触发时不产生额外请求。
- `scrapeOptions`（可选）：对排序后的候选依次抓取，失败换下一个候选，拿到一个有效正文即停（最多 `ADAPTER_SEARCH_SCRAPE_MAX_PAGES` 个）。失败候选带 `scrapeStatus`/`scrapeError`，不冒充成功。

### 5.2. 抓取有效性与能力矩阵

`/v2/scrape` 区分“拿到内容”和“拿到目标正文”。成功响应的 `metadata.scrapeStatus` 为 `ok` 或 `partial`（partial 同时返回 `warning`）；失败返回 `success: false` 与可识别 `code`：

| code | 含义 |
|------|------|
| `page_not_found` | 硬 404/410 或软 404（页面报不存在） |
| `access_restricted` | 反爬/登录墙/访问受限（不绕过） |
| `content_incomplete` | 页面壳或等待预算耗尽，正文未就绪 |
| `unsupported_format` | 无法解析的格式（如损坏/超限 PDF） |
| `fetch_failed` | requests 与浏览器两条路径都失败 |
| `scrape_timeout` | 总时间预算耗尽 |

能力矩阵（受限/失效页只保证分类正确，不保证内容）：

| 类型 | 支持 | 说明 |
|------|------|------|
| 静态 HTML | ✅ | requests 直接抓取 |
| 动态/延迟 JS 页 | ✅ | agent-browser 等待正文就绪（DOM 静默 + 文本规模），受总预算约束 |
| 文本型 PDF | ✅ | pypdf 按页提取；大小/页数超限报 partial 或 unsupported |
| 扫描/加密 PDF | ⚠️ 分类 | 提示需 OCR / 加密，不返回乱码假成功 |
| 登录/受限页 | ⚠️ 分类 | 返回 `access_restricted`，不绕过验证码与访问控制 |
| `timeout` / `waitFor` | ✅ | 单位均为**毫秒**；`timeout` 是总工作预算 |
| 正文清洗 | ✅ | 密度打分选正文容器并去导航噪声，保留代码/表格/链接 |

### 5.3. 效果验收与诊断

显式联网工具（不属于默认离线测试套件）：

```bash
python scripts/eval_baseline.py    # T01 功能效果基准（搜索 12 查询 + 抓取 12 页面）
python scripts/engine_probe.py     # T02 SearXNG 单引擎对照诊断
```

## 6. 配置

在 `.env` 中设置（从 `.env.example` 复制）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SEARXNG_BASE` | `http://127.0.0.1:3671` | SearXNG 地址 |
| `ADAPTER_HOST` | `127.0.0.1` | adapter 监听地址 |
| `ADAPTER_PORT` | `3672` | adapter 监听端口 |
| `ADAPTER_MAX_SEARCH_RESULTS` | `20` | 单次搜索最大条数 |
| `ADAPTER_MAX_SCRAPE` | `60000` | 单页抓取最大字符数 |
| `ADAPTER_CRAWL_TIMEOUT` | `300` | Crawl 开始执行后的整体超时（秒） |
| `ADAPTER_CRAWL_DEFAULT_LIMIT` | `10` | Crawl 默认页面数 |
| `ADAPTER_CRAWL_DEFAULT_DEPTH` | `1` | Crawl 默认发现深度 |
| `ADAPTER_MAX_CRAWL_LIMIT` | `100` | 单个 Crawl 最大页面数 |
| `ADAPTER_MAX_CRAWL_DEPTH` | `5` | 单个 Crawl 最大发现深度 |
| `ADAPTER_MAX_CRAWL_PATH_FILTERS` | `32` | include/exclude 各自最大规则数 |
| `ADAPTER_MAX_CRAWL_PATH_LENGTH` | `256` | 单条路径规则最大字符数 |
| `ADAPTER_MAX_ACTIVE_CRAWLS` | `4` | 同时执行的 Crawl 数 |
| `ADAPTER_MAX_QUEUED_CRAWLS` | `16` | 等待执行的 Crawl 数 |
| `ADAPTER_MAX_JOBS` | `100` | 最大保留终态任务数 |
| `ADAPTER_JOB_TTL` | `3600` | 终态任务保留时长（秒） |
| `ADAPTER_MAX_BODY_BYTES` | `2097152` | 请求体最大字节数 |
| `SEARXNG_PROXY` | `""` | SearXNG 代理（留空=无代理） |
| `SEARXNG_DISABLED_ENGINES` | `""` | 实测异常引擎局部隔离（逗号分隔） |
| `ADAPTER_SEARCH_MAX_ROUNDS` | `2` | 搜索轮次上限（1=不补搜） |
| `ADAPTER_SEARCH_SCRAPE_MAX_PAGES` | `3` | scrapeOptions 组合模式最大抓取页数 |
| `ADAPTER_SCRAPE_DEFAULT_TIMEOUT_MS` | `30000` | scrape 默认总预算（毫秒） |
| `ADAPTER_SCRAPE_MAX_TIMEOUT_MS` | `120000` | scrape 预算上限（毫秒） |
| `ADAPTER_MAX_PDF_BYTES` | `20971520` | PDF 最大字节数 |
| `ADAPTER_MAX_PDF_PAGES` | `100` | PDF 最大解析页数 |

## 7. 搜索引擎

**6 个引擎**（`searxng/settings.yml.template`，`start.sh` 根据 `.env` 生成）：

| 引擎 | 直连 | 说明 |
|------|------|------|
| 360搜索 | ✅ | 国内引擎，稳定 |
| Bing | ✅ | 国际，国内直连 |
| Google | ❌ 需代理 | 被墙 |
| Wikipedia | ❌ 需代理 | 被墙 |
| Yandex | ✅ | 中英文覆盖好 |
| Presearch | ✅ | 去中心化搜索 |

### 7.1. 代理

默认无代理。如需解封 Google/Wikipedia，在 `.env` 中设置：

```bash
SEARXNG_PROXY=http://host.docker.internal:7890
```

必须用 `host.docker.internal`（容器内 `127.0.0.1` 指向自身）。改后重启生效。无代理时仅 bing/yandex/360 可用（~23 条）。

### 7.2. 兜底

SearXNG 返回空时自动切 Bing HTML scrape（国内直连，中文友好）。

### 7.3. 已禁用

百度/搜狗（CAPTCHA）、DuckDuckGo/Mojeek（不稳定）、Brave/Startpage/Qwant/Yahoo/Naver 等。

## 8. 开发

```bash
pytest                          # 测试
ruff check adapter/ tests/      # lint
mypy adapter/                   # 类型检查
```
