#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""百度网盘：按图片名称精准搜索并批量下载"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from baidu_client import BaiduPanClient
from config_store import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    is_cookie_configured,
    load_config_optional,
    save_config,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_NAMES_FILE = ROOT / "names.txt"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print("还没有配置登录信息。")
        print("请双击「点我启动.bat」，在网页里完成登录和下载。")
        sys.exit(1)
    cfg = load_config_optional()
    if not is_cookie_configured(cfg.get("cookies", "")):
        print("还没有登录百度网盘，请先打开配置页面完成第 1 步登录。")
        sys.exit(1)
    return cfg


def parse_names_text(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in re.split(r"[,，;；\s]+", line):
            name = part.strip()
            if not name or name.startswith("#") or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def load_names_from_file(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return parse_names_text(f.read())


def run_download(
    names: list[str],
    search_dir: str,
    download_dir: Path,
    recursive: bool,
    dry_run: bool,
) -> None:
    config = load_config()
    client = BaiduPanClient.from_cookie_string(config["cookies"])

    print("正在验证登录...")
    client.bdstoken
    print("登录有效\n")

    download_dir.mkdir(parents=True, exist_ok=True)
    ok, skip, fail = 0, 0, 0

    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] 查询: {name}")
        try:
            item, dup_count = client.find_exact_image(name, search_dir, recursive)
            if not item:
                print(f"  ✗ 未找到精准匹配的图片\n")
                fail += 1
                continue

            remote_path = item.get("path") or ""
            server_name = (
                item.get("server_filename") or item.get("filename") or name
            )
            if dup_count > 1:
                print(f"  ! 发现 {dup_count} 个同名文件，仅下载第一个: {remote_path}")

            local_path = download_dir / server_name
            if local_path.exists():
                print(f"  - 本地已存在，跳过: {local_path}\n")
                skip += 1
                continue

            if dry_run:
                print(f"  [试运行] 将下载: {remote_path} -> {local_path}\n")
                ok += 1
                continue

            print(f"  → 下载: {remote_path}")
            client.download_file(remote_path, local_path)
            print(f"  ✓ 已保存: {local_path}\n")
            ok += 1
            time.sleep(0.8)
        except Exception as e:
            print(f"  ✗ 失败: {e}\n")
            fail += 1

    print("=" * 40)
    print(f"完成: 成功 {ok} | 跳过 {skip} | 失败 {fail} | 共 {len(names)}")


def cmd_setup(_: argparse.Namespace) -> None:
    if CONFIG_FILE.exists():
        print(f"config.json 已存在: {CONFIG_FILE}")
        return
    save_config(dict(DEFAULT_CONFIG))
    print(f"已创建 {CONFIG_FILE}")
    print("接下来请打开配置页面，用浏览器登录百度网盘。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="百度网盘：按图片名称精准匹配并批量下载"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="从模板创建 config.json")

    p_dl = sub.add_parser("download", help="批量下载图片")
    p_dl.add_argument(
        "-f",
        "--file",
        type=Path,
        default=DEFAULT_NAMES_FILE,
        help=f"名称列表文件（默认 {DEFAULT_NAMES_FILE.name}）",
    )
    p_dl.add_argument("names", nargs="*", help="也可直接在命令行传入文件名")
    p_dl.add_argument(
        "-d",
        "--dir",
        help="网盘搜索目录，默认使用 config.json 中的 search_dir",
    )
    p_dl.add_argument(
        "-o",
        "--output",
        type=Path,
        help="本地下载目录，默认使用 config.json 中的 download_dir",
    )
    p_dl.add_argument(
        "--no-recursive",
        action="store_true",
        help="不递归搜索子目录",
    )
    p_dl.add_argument(
        "--dry-run",
        action="store_true",
        help="只查询不下载",
    )

    args = parser.parse_args()
    if args.command is None:
        print("新手推荐：双击「点我启动.bat」打开图形界面。")
        print()
        parser.print_help()
        return

    if args.command == "setup":
        cmd_setup(args)
        return

    if args.command == "download":
        config = load_config()
        names: list[str] = list(args.names)
        if args.file.exists():
            names.extend(load_names_from_file(args.file))
        elif args.names:
            pass
        else:
            print(f"请创建 {args.file} 或在命令行传入文件名")
            print("示例: python main.py download 图片1.jpg 图片2.png")
            sys.exit(1)

        # 去重并保持顺序
        seen: set[str] = set()
        unique_names: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique_names.append(n)

        if not unique_names:
            print("没有要下载的文件名")
            sys.exit(1)

        search_dir = args.dir or config.get("search_dir", "/")
        download_dir = args.output or Path(config.get("download_dir", "downloads"))
        if not download_dir.is_absolute():
            download_dir = ROOT / download_dir
        recursive = not args.no_recursive and config.get("recursive", True)

        run_download(
            unique_names,
            search_dir=search_dir,
            download_dir=download_dir,
            recursive=recursive,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
