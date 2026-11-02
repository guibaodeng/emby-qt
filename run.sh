#!/usr/bin/env bash
# 启动 EmbyQt。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
# libmpv 要求数字 locale 为 C
export LC_NUMERIC=C

# 系统若缺少 libxcb-cursor0，使用随仓库附带的一份，保证 Qt xcb 后端可用
if [ -d "$ROOT/vendor/lib" ]; then
    export LD_LIBRARY_PATH="$ROOT/vendor/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "未找到虚拟环境，请先执行：" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

exec "$PY" -m embyqt "$@"
