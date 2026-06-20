#!/usr/bin/env bash
# 从 ~/.claude/settings.json 的 permissions.deny 移除 WebSearch
# 恢复 Claude Code 内置 web search（与 MCP firecrawl 并存，模型自行选择）
set -e
. "$(dirname "$0")/_env.sh"

SETTINGS=~/.claude/settings.json
[ -f "$SETTINGS" ] || { echo "无 $SETTINGS，无需操作"; exit 0; }

python3 - "$SETTINGS" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)
deny = d.get("permissions", {}).get("deny", [])
if "WebSearch" in deny:
    deny.remove("WebSearch")
    if not deny:
        d.get("permissions", {}).pop("deny", None)
        if not d.get("permissions"):
            d.pop("permissions", None)
    with open(path, "w") as f:
        json.dump(d, f, indent=2)
        f.write("\n")
    print("  ✓ 已从 permissions.deny 移除 WebSearch")
else:
    print("  • WebSearch 本就不在 deny 列表，无需操作")
PY

echo "==> 完成: $SETTINGS"
