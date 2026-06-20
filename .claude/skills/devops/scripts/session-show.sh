#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

SESSION="${AGENT_BROWSER_SESSION_NAME:-default}"
STATE_FILE=~/.agent-browser/sessions/${SESSION}-default.json

echo "=== session: $SESSION ==="
if [ ! -f "$STATE_FILE" ]; then
  echo "  无保存的 state 文件（$STATE_FILE）"
  echo "  先用 login.sh 登录站点"
  exit 0
fi

python3 -c "
import json, sys
with open('$STATE_FILE') as f:
    d = json.load(f)
cookies = d.get('cookies', [])
origins = d.get('origins', [])
print(f'  cookies: {len(cookies)}')
for c in cookies:
    print(f'    {c.get(\"name\")}={c.get(\"value\",\"\")[:30]}  domain={c.get(\"domain\")}')
print(f'  localStorage origins: {len(origins)}')
for o in origins:
    print(f'    {o.get(\"origin\")}: {len(o.get(\"localStorage\",[]))} items')
"
