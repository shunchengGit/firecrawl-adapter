#!/usr/bin/env bash
# 在 ~/.claude/settings.json 的 permissions.deny 加入 WebSearch
# 强制 Claude Code 模型走 MCP firecrawl 工具，禁用内置 web search
set -e
. "$(dirname "$0")/_env.sh"

SETTINGS=~/.claude/settings.json
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

python3 - "$SETTINGS" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)
perm = d.setdefault("permissions", {})
deny = perm.setdefault("deny", [])
if "WebSearch" not in deny:
    deny.append("WebSearch")
with open(path, "w") as f:
    json.dump(d, f, indent=2)
    f.write("\n")
print("  ✓ 已在 permissions.deny 加入 WebSearch")
PY

echo "==> 完成: $SETTINGS"
echo "    重启 Claude Code 会话生效"
