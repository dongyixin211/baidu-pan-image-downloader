#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地配置页面：在浏览器里填写 Cookie、图片编号并下载"""

from __future__ import annotations

import os
import re
import socket
import threading
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from baidu_client import BaiduPanClient
from browser_login import run_browser_login
from config_store import (
    CONFIG_FILE,
    is_cookie_configured,
    load_config_optional,
    save_config,
)
from main import DEFAULT_NAMES_FILE, ROOT, load_config, run_download

WEB_DIR = ROOT / "web"
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")

_download_lock = threading.Lock()
_download_running = False
_download_logs: list[str] = []
_download_result: dict[str, Any] | None = None

_login_lock = threading.Lock()
_login_running = False
_login_status = "未开始"
_login_error: str | None = None


def find_free_port(preferred: int, attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"端口 {preferred}-{preferred + attempts - 1} 都被占用")


def parse_names_text(text: str) -> list[str]:
    """从粘贴文本解析编号：支持逗号、换行、空格、分号分隔"""
    seen: set[str] = set()
    names: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in re.split(r"[,，;；\s]+", line):
            part = part.strip()
            if not part or part.startswith("#") or part in seen:
                continue
            seen.add(part)
            names.append(part)
    return names


def save_names_file(names: list[str]) -> None:
    lines = ["# 每行一个图片文件名或编号（无扩展名也可）", ""]
    lines.extend(names)
    DEFAULT_NAMES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask_cookie(cookie: str) -> str:
    if not cookie or len(cookie) < 20:
        return ""
    return cookie[:12] + " …… " + cookie[-8:]


@app.route("/")
def index() -> Any:
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/api/config")
def api_get_config() -> Any:
    cfg = load_config_optional()
    has_cookie = is_cookie_configured(cfg.get("cookies", ""))
    return jsonify(
        {
            "cookies_set": has_cookie,
            "cookies_preview": mask_cookie(cfg.get("cookies", "")) if has_cookie else "",
            "search_dir": cfg.get("search_dir", "/"),
            "download_dir": cfg.get("download_dir", "downloads"),
            "recursive": bool(cfg.get("recursive", True)),
        }
    )


@app.post("/api/config")
def api_save_config() -> Any:
    data = request.get_json(silent=True) or {}
    cfg = load_config_optional()

    new_cookie = (data.get("cookies") or "").strip()
    if new_cookie:
        if not is_cookie_configured(new_cookie):
            return jsonify(
                {
                    "ok": False,
                    "error": "Cookie 不完整：请复制包含 BDUSS= 的完整 Cookie，或直接点击「浏览器登录」。",
                }
            ), 400
        cfg["cookies"] = new_cookie

    search_dir = (data.get("search_dir") or "/").strip() or "/"
    if "\\" in search_dir or (len(search_dir) > 1 and search_dir[1] == ":"):
        return jsonify(
            {
                "ok": False,
                "error": "网盘搜索目录应填写网盘路径（如 / 或 /我的图片），不要填电脑本地路径",
            }
        ), 400
    if not search_dir.startswith("/"):
        return jsonify(
            {
                "ok": False,
                "error": "网盘搜索目录要以 / 开头，例如 / 或 /商品图片。",
            }
        ), 400

    cfg["search_dir"] = search_dir
    cfg["download_dir"] = (data.get("download_dir") or "downloads").strip() or "downloads"
    cfg["recursive"] = bool(data.get("recursive", True))

    try:
        save_config(cfg)
    except Exception as e:
        return jsonify({"ok": False, "error": f"保存失败: {e}"}), 500
    message = "设置已保存"
    if not is_cookie_configured(cfg.get("cookies", "")):
        message = "设置已保存。下载前还需要先登录百度网盘"
    return jsonify({"ok": True, "message": message})


@app.get("/api/names")
def api_get_names() -> Any:
    if DEFAULT_NAMES_FILE.exists():
        text = DEFAULT_NAMES_FILE.read_text(encoding="utf-8")
        names = parse_names_text(text)
        return jsonify({"names": names, "text": "\n".join(names)})
    return jsonify({"names": [], "text": ""})


@app.post("/api/names")
def api_save_names() -> Any:
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    names = parse_names_text(text) if text else list(data.get("names") or [])
    if not names:
        return jsonify({"ok": False, "error": "请至少填写一个图片编号或文件名"}), 400
    save_names_file(names)
    return jsonify({"ok": True, "count": len(names), "message": f"已保存 {len(names)} 个编号到 names.txt"})


def _run_browser_login_job() -> None:
    global _login_running, _login_status, _login_error

    def on_status(msg: str) -> None:
        global _login_status
        _login_status = msg

    try:
        cookie_str = run_browser_login(on_status=on_status)
        cfg = load_config_optional()
        cfg["cookies"] = cookie_str
        save_config(cfg)
        client = BaiduPanClient.from_cookie_string(cookie_str)
        client.bdstoken
        _login_status = "登录成功，Cookie 已自动保存"
        _login_error = None
    except Exception as e:
        _login_error = str(e)
        _login_status = "登录失败"
    finally:
        _login_running = False


@app.post("/api/login/browser")
def api_browser_login() -> Any:
    global _login_running, _login_status, _login_error
    with _login_lock:
        if _login_running:
            return jsonify({"ok": False, "error": "已有登录窗口在进行中"}), 409
        _login_running = True
        _login_status = "正在启动…"
        _login_error = None

    thread = threading.Thread(target=_run_browser_login_job, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "已打开浏览器，请在弹出窗口中登录百度网盘"})


@app.get("/api/login/status")
def api_login_status() -> Any:
    cfg = load_config_optional()
    return jsonify(
        {
            "running": _login_running,
            "status": _login_status,
            "error": _login_error,
            "cookies_set": is_cookie_configured(cfg.get("cookies", "")),
            "cookies_preview": mask_cookie(cfg.get("cookies", ""))
            if cfg.get("cookies")
            else "",
        }
    )


@app.post("/api/test-login")
def api_test_login() -> Any:
    try:
        cfg = load_config_optional()
        if not is_cookie_configured(cfg.get("cookies", "")):
            return jsonify({"ok": False, "error": "还没有登录，请先点击「浏览器登录」。"}), 400
        client = BaiduPanClient.from_cookie_string(cfg["cookies"])
        token = client.bdstoken
        return jsonify({"ok": True, "message": f"登录有效（bdstoken: {token[:8]}…）"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


def _run_download_job(names: list[str], dry_run: bool) -> None:
    global _download_running, _download_logs, _download_result
    _download_logs = []
    _download_result = None

    class Tee:
        def write(self, s: str) -> None:
            if s:
                _download_logs.append(s)

        def flush(self) -> None:
            pass

    import sys

    old_stdout = sys.stdout
    sys.stdout = Tee()
    try:
        cfg = load_config()
        search_dir = cfg.get("search_dir", "/")
        download_dir = Path(cfg.get("download_dir", "downloads"))
        if not download_dir.is_absolute():
            download_dir = ROOT / download_dir
        recursive = bool(cfg.get("recursive", True))
        run_download(names, search_dir, download_dir, recursive, dry_run)
        _download_result = {"ok": True}
    except Exception as e:
        _download_logs.append(f"\n错误: {e}\n")
        _download_result = {"ok": False, "error": str(e)}
    finally:
        sys.stdout = old_stdout
        _download_running = False


@app.post("/api/download")
def api_download() -> Any:
    global _download_running
    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run", False))

    text = data.get("text", "")
    names = parse_names_text(text) if text else list(data.get("names") or [])
    if not names and DEFAULT_NAMES_FILE.exists():
        names = parse_names_text(DEFAULT_NAMES_FILE.read_text(encoding="utf-8"))

    if not names:
        return jsonify({"ok": False, "error": "没有要下载的编号，请先填写并保存列表"}), 400

    cfg = load_config_optional()
    if not is_cookie_configured(cfg.get("cookies", "")):
        return jsonify({"ok": False, "error": "请先完成第 1 步：浏览器登录。"}), 400

    with _download_lock:
        if _download_running:
            return jsonify({"ok": False, "error": "已有下载任务在进行中，请稍候"}), 409
        _download_running = True

    save_names_file(names)
    thread = threading.Thread(
        target=_run_download_job, args=(names, dry_run), daemon=True
    )
    thread.start()
    return jsonify(
        {"ok": True, "message": "已开始" + ("查询" if dry_run else "下载"), "count": len(names)}
    )


@app.get("/api/download/status")
def api_download_status() -> Any:
    return jsonify(
        {
            "running": _download_running,
            "logs": "".join(_download_logs),
            "result": _download_result,
        }
    )


@app.post("/api/open-download-folder")
def api_open_download_folder() -> Any:
    cfg = load_config_optional()
    download_dir = Path(cfg.get("download_dir", "downloads"))
    if not download_dir.is_absolute():
        download_dir = ROOT / download_dir
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(download_dir)  # type: ignore[attr-defined]
        else:
            webbrowser.open(download_dir.as_uri())
        return jsonify({"ok": True, "path": str(download_dir)})
    except Exception as e:
        return jsonify({"ok": False, "error": f"打开下载文件夹失败: {e}"}), 500


@app.get("/api/health")
def api_health() -> Any:
    return jsonify({"ok": True})


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="打开本地配置页面")
    parser.add_argument("--port", type=int, default=8765, help="端口（默认 8765）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    port = find_free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    if not CONFIG_FILE.exists():
        save_config(load_config_optional())
        print("首次使用：已创建默认配置文件")
    if port != args.port:
        print(f"端口 {args.port} 被占用，已自动改用 {port}")
    print(f"配置页面: {url}")
    print("关闭此窗口即可停止服务")
    if not args.no_browser:
        webbrowser.open(url)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
