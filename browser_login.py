"""打开浏览器登录百度网盘，并从 Edge/Chrome 自动读取 Cookie"""

from __future__ import annotations

import platform
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
PAN_URL = "https://pan.baidu.com/disk/home"


def cookies_to_string(cookie_dict: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())


def read_baidu_cookies_from_system() -> str | None:
    """从本机 Edge / Chrome 读取 .baidu.com 的 Cookie"""
    try:
        import browser_cookie3
    except ImportError as e:
        raise RuntimeError(
            "缺少依赖 browser-cookie3，请运行: pip install browser-cookie3"
        ) from e

    for browser_name in ("edge", "chrome"):
        try:
            loader = getattr(browser_cookie3, browser_name)
            jar = loader(domain_name=".baidu.com")
        except Exception:
            continue

        seen: set[str] = set()
        parts: list[str] = []
        for c in jar:
            if c.name in seen:
                continue
            seen.add(c.name)
            parts.append(f"{c.name}={c.value}")

        if any(p.startswith("BDUSS=") for p in parts):
            return "; ".join(parts)

    return None


def open_pan_in_browser() -> None:
    """尽量用 Edge 打开（便于读取 Cookie），否则用系统默认浏览器"""
    if platform.system() == "Darwin":
        for app_name in ("Microsoft Edge", "Google Chrome"):
            try:
                subprocess.Popen(
                    ["open", "-a", app_name, PAN_URL],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception:
                continue
    else:
        edge_paths = [
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ]
        for edge in edge_paths:
            if edge.exists():
                subprocess.Popen(
                    [str(edge), PAN_URL],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
    webbrowser.open(PAN_URL)


def run_browser_login(
    on_status: Callable[[str], None] | None = None,
    timeout_sec: int = 600,
) -> str:
    def status(msg: str) -> None:
        if on_status:
            on_status(msg)

    status("正在打开浏览器（请使用 Edge 或 Chrome 登录）…")
    open_pan_in_browser()
    status("请在浏览器中登录百度网盘，登录成功后会自动保存（无需复制 Cookie）")

    for i in range(timeout_sec):
        cookie_str = read_baidu_cookies_from_system()
        if cookie_str and "BDUSS=" in cookie_str:
            status("已读取登录信息，正在保存…")
            return cookie_str
        if i % 8 == 0:
            status("等待登录… 请确认已在 Edge 或 Chrome 中打开并登录 pan.baidu.com")
        time.sleep(1)

    raise TimeoutError(
        "未检测到登录。请用 Edge 或 Chrome 打开 pan.baidu.com 完成登录后重试；"
        "若已登录仍失败，可展开下方「手动粘贴 Cookie」。"
    )
