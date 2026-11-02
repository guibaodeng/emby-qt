#!/usr/bin/env bash
# 打包 EmbyQt 为 Linux 可执行文件（PyInstaller）。
#
# 用法：
#   ./scripts/build_binary.sh                 # 目录版，自动携带系统 libVLC
#   ./scripts/build_binary.sh --onefile       # 单文件版
#   ./scripts/build_binary.sh --system-vlc    # 不打包 libVLC，运行时要求系统已安装 VLC
#   ./scripts/build_binary.sh --help
#
# 产物：
#   目录版：dist/EmbyQt/EmbyQt
#   单文件：dist/EmbyQt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_NAME="EmbyQt"
PY="$ROOT/.venv/bin/python"
MODE="onedir"
VLC_MODE="auto"       # auto | bundle | system
BUNDLE_VLC=0

usage() {
    cat <<'USAGE'
打包 EmbyQt 为 Linux 可执行文件（PyInstaller）。

用法：
  ./scripts/build_binary.sh                 # 目录版，自动携带系统 libVLC
  ./scripts/build_binary.sh --onefile       # 单文件版
  ./scripts/build_binary.sh --system-vlc    # 不打包 libVLC，运行时要求系统已安装 VLC
  ./scripts/build_binary.sh --help

产物：
  目录版：dist/EmbyQt/EmbyQt
  单文件：dist/EmbyQt
USAGE
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --onefile) MODE="onefile" ;;
        --onedir) MODE="onedir" ;;
        --system-vlc) VLC_MODE="system" ;;
        --bundle-vlc) VLC_MODE="bundle" ;;
        --help|-h) usage ;;
        *) echo "未知参数：$arg" >&2; usage ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "此脚本面向 Linux。macOS 需要单独处理 .app 和签名。" >&2
    exit 1
fi

echo "==> 检查 Python 环境"
if [[ ! -x "$PY" ]]; then
    echo "未找到 .venv，正在创建..."
    python3 -m venv "$ROOT/.venv"
fi
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -r "$ROOT/requirements.txt"
if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "==> 安装 PyInstaller"
    "$PY" -m pip install -q "pyinstaller>=6.10"
fi

find_lib() {
    local name="$1" path=""
    if command -v ldconfig >/dev/null 2>&1; then
        path="$(ldconfig -p 2>/dev/null | awk -v n="$name" '$1==n {print $NF; exit}')"
    fi
    if [[ -z "$path" ]]; then
        path="$(find /usr/lib /usr/lib64 /lib -name "$name" \( -type f -o -type l \) 2>/dev/null | head -n1 || true)"
    fi
    [[ -n "$path" ]] && printf '%s\n' "$path"
}

VLC_LIB="$(find_lib libvlc.so.5 || true)"
VLC_CORE="$(find_lib libvlccore.so.9 || true)"
VLC_PLUGINS=""
if [[ -n "$VLC_LIB" ]]; then
    candidate="$(dirname "$(readlink -f "$VLC_LIB")")/vlc/plugins"
    [[ -d "$candidate" ]] && VLC_PLUGINS="$candidate"
fi

if [[ "$VLC_MODE" == "bundle" ]]; then
    if [[ -z "$VLC_LIB" || -z "$VLC_CORE" || -z "$VLC_PLUGINS" ]]; then
        echo "找不到 libVLC/libvlccore/plugins。请先安装 VLC（如 sudo apt install vlc）。" >&2
        exit 1
    fi
    BUNDLE_VLC=1
elif [[ "$VLC_MODE" == "auto" && -n "$VLC_LIB" && -n "$VLC_CORE" && -n "$VLC_PLUGINS" ]]; then
    BUNDLE_VLC=1
fi

if [[ "$BUNDLE_VLC" == "0" ]]; then
    echo "==> 不打包 libVLC：运行环境必须已安装 VLC/libVLC"
    if ! "$PY" -c "import vlc" >/dev/null 2>&1; then
        echo "警告：当前环境也找不到可用的 libVLC，打包后可能无法播放。" >&2
    fi
fi

BUILD="$ROOT/build"
mkdir -p "$BUILD"
cat > "$BUILD/entry.py" <<'PYENTRY'
from embyqt.main import main

raise SystemExit(main())
PYENTRY

ARGS=(
    --noconfirm
    --clean
    --windowed
    --log-level WARN
    --name "$APP_NAME"
    --paths "$ROOT"
    --distpath "$ROOT/dist"
    --workpath "$BUILD/pyinstaller"
    --specpath "$BUILD"
    --hidden-import vlc
    --hidden-import PySide6.QtSvg
    --add-data "$ROOT/embyqt/assets:embyqt/assets"
)
[[ "$MODE" == "onefile" ]] && ARGS+=(--onefile) || ARGS+=(--onedir)

# libxcb-cursor 备用库：统一成加载器实际查找的文件名
if [[ -f "$ROOT/vendor/lib/libxcb-cursor.so.0.0.0" ]]; then
    mkdir -p "$BUILD/xcb"
    cp -L "$ROOT/vendor/lib/libxcb-cursor.so.0.0.0" "$BUILD/xcb/libxcb-cursor.so.0"
    ARGS+=(--add-binary "$BUILD/xcb/libxcb-cursor.so.0:.")
fi

if [[ "$BUNDLE_VLC" == "1" ]]; then
    echo "==> 打包 libVLC：$VLC_LIB"
    mkdir -p "$BUILD/vlc/lib" "$BUILD/vlc/runtime"
    cp -L "$VLC_LIB" "$BUILD/vlc/lib/libvlc.so.5"
    cp -L "$VLC_CORE" "$BUILD/vlc/lib/libvlccore.so.9"
    rm -rf "$BUILD/vlc/plugins"
    cp -a "$VLC_PLUGINS" "$BUILD/vlc/plugins"

    cat > "$BUILD/vlc/runtime/vlc_runtime.py" <<'PYHOOK'
import ctypes
import os
import sys

base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
lib = os.path.join(base, "libvlc.so.5")
core = os.path.join(base, "libvlccore.so.9")
if os.path.exists(core):
    # 先加载 core，确保 libvlc 的 NEEDED 不会被解析到系统旧版本
    ctypes.CDLL(core, mode=ctypes.RTLD_GLOBAL)
if os.path.exists(lib):
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", lib)
    os.environ.setdefault("VLC_PLUGIN_PATH", os.path.join(base, "vlc", "plugins"))
    old = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = base + ((":" + old) if old else "")
PYHOOK

    ARGS+=(
        --add-binary "$BUILD/vlc/lib/libvlc.so.5:."
        --add-binary "$BUILD/vlc/lib/libvlccore.so.9:."
        --add-data "$BUILD/vlc/plugins:vlc/plugins"
        --runtime-hook "$BUILD/vlc/runtime/vlc_runtime.py"
    )
fi

echo "==> 开始打包（$MODE）"
"$PY" -m PyInstaller "${ARGS[@]}" "$BUILD/entry.py"

if [[ "$MODE" == "onefile" ]]; then
    OUT="$ROOT/dist/$APP_NAME"
else
    OUT="$ROOT/dist/$APP_NAME/$APP_NAME"
fi
echo
mkdir -p "$ROOT/dist"
cp -f "$ROOT/packaging/embyqt.desktop" "$ROOT/dist/embyqt.desktop"
cp -f "$ROOT/packaging/embyqt.png" "$ROOT/dist/embyqt.png"
echo "==> 打包完成：$OUT"
echo "运行：$OUT"
echo "桌面文件：$ROOT/dist/embyqt.desktop（安装后 Exec=/opt/EmbyQt/EmbyQt）"
echo "图标：$ROOT/dist/embyqt.png"
if [[ "$BUNDLE_VLC" == "0" ]]; then
    echo "提示：目标机器必须安装 VLC/libVLC。"
fi
