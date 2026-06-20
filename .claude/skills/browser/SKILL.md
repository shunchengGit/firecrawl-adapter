---
name: browser
description: agent-browser cookie/登录态管理。手动登录、查看 cookie、清除登录态。当用户提到"浏览器登录""查看 cookie""清除登录态"等时使用。
cli_version: ">=1.0.0"
---

# browser — agent-browser 登录态管理

手动登录一次，cookie 自动链式传递给后续所有 session（Hermes / adapter）。

## 用法

所有脚本从项目根目录运行：

```bash
.claude/skills/browser/scripts/browser-login.sh <url>     # 登录
.claude/skills/browser/scripts/browser-session-show.sh     # 查看 cookie
.claude/skills/browser/scripts/browser-session-clear.sh    # 清除
```

## 原理

`AGENT_BROWSER_SESSION_NAME=firecrawl-adapter`（`~/.zshrc`）启用 agent-browser 的 state 持久化。每个 session 关闭时自动保存 cookie 到 `firecrawl-adapter-*.json`，新 session 打开时自动从最新文件加载，形成继承链。
