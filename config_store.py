"""读写 config.json（Cookie 含特殊字符时也能正确保存）"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "cookies": "",
    "search_dir": "/",
    "download_dir": "downloads",
    "recursive": True,
}


def is_cookie_configured(cookie: str | None) -> bool:
    """只把真正包含 BDUSS= 的 Cookie 视为已登录。"""
    return bool(cookie and "BDUSS=" in cookie)


def normalize_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(DEFAULT_CONFIG)
    if cfg:
        data.update(cfg)
    if not is_cookie_configured(str(data.get("cookies", ""))):
        data["cookies"] = ""
    data["search_dir"] = str(data.get("search_dir") or "/").strip() or "/"
    data["download_dir"] = str(data.get("download_dir") or "downloads").strip() or "downloads"
    data["recursive"] = bool(data.get("recursive", True))
    return data


def save_config(cfg: dict[str, Any]) -> None:
    cfg = normalize_config(cfg)
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _repair_broken_config(text: str) -> dict[str, Any] | None:
    """从格式损坏的 config.json 中尽量恢复字段"""
    cfg = dict(DEFAULT_CONFIG)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('"cookies":'):
            prefix = '"cookies": "'
            idx = line.find(prefix)
            if idx < 0:
                continue
            content = line[idx + len(prefix) :]
            if content.endswith('",'):
                content = content[:-2]
            elif content.endswith('"'):
                content = content[:-1]
            cfg["cookies"] = content.replace('\\"', '"')
            break

    for key, default in (("search_dir", "/"), ("download_dir", "downloads")):
        km = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text)
        if km:
            cfg[key] = km.group(1)
    rm = re.search(r'"recursive"\s*:\s*(true|false)', text, re.I)
    if rm:
        cfg["recursive"] = rm.group(1).lower() == "true"
    return cfg if cfg.get("cookies") else None


def load_config_optional() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    text = CONFIG_FILE.read_text(encoding="utf-8")
    try:
        return normalize_config(json.loads(text))
    except json.JSONDecodeError:
        repaired = _repair_broken_config(text)
        if repaired:
            save_config(repaired)
            return normalize_config(repaired)
        return dict(DEFAULT_CONFIG)


def merge_and_save(
    *,
    cookies: str | None = None,
    search_dir: str | None = None,
    download_dir: str | None = None,
    recursive: bool | None = None,
) -> dict[str, Any]:
    cfg = load_config_optional()
    if cookies is not None and cookies.strip():
        cfg["cookies"] = cookies.strip()
    if search_dir is not None:
        cfg["search_dir"] = search_dir
    if download_dir is not None:
        cfg["download_dir"] = download_dir
    if recursive is not None:
        cfg["recursive"] = recursive
    save_config(cfg)
    return cfg
