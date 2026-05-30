#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新手启动器：检查依赖，启动网页工具，并在出错时保留窗口。"""

from __future__ import annotations

import importlib
import subprocess
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIREMENTS_FILE = ROOT / "requirements.txt"
REQUIRED_MODULES = ("flask", "requests", "browser_cookie3")


def wait_before_exit() -> None:
    try:
        input("\n按回车键关闭窗口...")
    except EOFError:
        pass


def missing_modules() -> list[str]:
    missing: list[str] = []
    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    return missing


def ensure_dependencies() -> None:
    if sys.version_info < (3, 8):
        raise RuntimeError("Python 版本过低，请安装 Python 3.8 或更高版本。")

    missing = missing_modules()
    if not missing:
        print("运行环境检查通过。")
        return

    print("第一次启动需要安装依赖。")
    print("正在自动安装，请保持网络连接...")
    if not REQUIREMENTS_FILE.exists():
        raise RuntimeError(f"缺少依赖清单: {REQUIREMENTS_FILE}")

    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)]
    )

    still_missing = missing_modules()
    if still_missing:
        raise RuntimeError("依赖安装后仍缺少: " + ", ".join(still_missing))


def main() -> int:
    print()
    print("百度网盘图片批量下载工具")
    print("=" * 32)
    print("请保持这个窗口打开。网页工具关闭后，再关闭本窗口。")
    print()

    ensure_dependencies()

    from web_app import main as run_web_app

    run_web_app()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n工具已停止。")
        raise SystemExit(0)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code:
            wait_before_exit()
        raise
    except Exception:
        print("\n启动失败，错误信息如下：")
        traceback.print_exc()
        print("\n可以把上面的错误截图发给维护人员。")
        wait_before_exit()
        raise SystemExit(1)
