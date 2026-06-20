#!/usr/bin/env bash
# 查看 agent-browser session 中保存的 cookie（从 state 文件读取）
. "$(dirname "$0")/_env.sh"

echo "=== agent-browser session state ==="
if [ ! -d ~/.agent-browser/sessions ]; then
  echo "  无 sessions 目录"
  echo "  先用 browser-login.sh 登录站点"
  exit 0
fi

python3 -c "
import json, os, glob

sessions_dir = os.path.expanduser('~/.agent-browser/sessions')
files = glob.glob(os.path.join(sessions_dir, '*.json'))
if not files:
    print('  无 state 文件')
    exit()

# 按修改时间排序，最新的在前
files.sort(key=os.path.getmtime, reverse=True)
print(f'  state 文件 ({len(files)} 个):')
for f in files:
    name = os.path.basename(f)
    size = os.path.getsize(f)
    try:
        with open(f) as fh:
            d = json.load(fh)
        cookies = d.get('cookies', [])
        print(f'    {name} ({size}B, {len(cookies)} cookies)')
        for c in cookies:
            print(f'      {c.get(\"domain\",\"?\")}  {c.get(\"name\",\"?\")}={c.get(\"value\",\"\")[:40]}')
    except Exception as e:
        print(f'    {name} ({size}B, 解析失败: {e})')
"
