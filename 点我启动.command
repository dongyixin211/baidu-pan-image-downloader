#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "正在启动百度网盘图片批量下载工具..."

if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="python"
else
  echo
  echo "没有找到可用的 Python 3.8 或更高版本。"
  echo "请先安装 Python: https://www.python.org/downloads/macos/"
  echo
  read -r -p "按回车键关闭窗口..."
  exit 1
fi

"$PYTHON_CMD" launcher.py "$@"
echo
read -r -p "工具已关闭，按回车键关闭窗口..."
