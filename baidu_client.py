"""百度网盘客户端：按文件名搜索并下载（Cookie 登录）"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
import requests

PAN_API = "https://pan.baidu.com/api"
PAN_HOME = "https://pan.baidu.com/disk/home"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://pan.baidu.com/disk/home",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".heic", ".ico"}

# 百度 dlink / locatedownload 下载时必须使用的 UA（Chrome UA 会 403）
DOWNLOAD_HEADER_SETS = [
    {
        "User-Agent": "pan.baidu.com",
        "Referer": "https://pan.baidu.com/",
    },
    {
        "User-Agent": "netdisk;7.0.0.6;PC;PC-Windows;10.0.22621;WindowsBaiduYun",
        "Referer": "https://pan.baidu.com/disk/home",
    },
    {
        "User-Agent": "softxm;netdisk",
        "Referer": "https://pan.baidu.com/disk/home",
        "Connection": "Keep-Alive",
    },
]

PCS_UA = "softxm;netdisk"
LOCATE_DOWNLOAD_KEY = "ebrcUYiuxaZv2XGu7KIYKxUrqfnOfpDF"



def parse_cookies(cookie_str: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        cookies[key.strip()] = value.strip()
    if "BDUSS" not in cookies:
        raise ValueError("Cookie 中缺少 BDUSS，请从浏览器重新复制完整 Cookie")
    return cookies


class BaiduPanClient:
    def __init__(self, cookies: Dict[str, str]):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.cookies.update(cookies)
        self.bduss = cookies["BDUSS"]
        self._bdstoken: Optional[str] = None
        self._user_id: Optional[int] = None

    @classmethod
    def from_cookie_string(cls, cookie_str: str) -> "BaiduPanClient":
        return cls(parse_cookies(cookie_str))

    @property
    def bdstoken(self) -> str:
        if self._bdstoken:
            return self._bdstoken
        resp = self.session.get(PAN_HOME, timeout=30)
        resp.raise_for_status()
        patterns = [
            r'"bdstoken"\s*:\s*"([0-9a-f]+)"',
            r"bdstoken['\":\s]+([0-9a-f]{32})",
        ]
        for pattern in patterns:
            match = re.search(pattern, resp.text)
            if match:
                self._bdstoken = match.group(1)
                return self._bdstoken
        raise RuntimeError("无法获取 bdstoken，请检查 Cookie 是否有效或已过期")

    def _base_params(self) -> Dict[str, str]:
        return {
            "app_id": "250528",
            "BDUSS": self.bduss,
            "bdstoken": self.bdstoken,
            "t": str(int(time.time())),
        }

    def search_files(
        self,
        keyword: str,
        search_dir: str = "/",
        recursive: bool = True,
        page_size: int = 100,
    ) -> List[dict]:
        """按关键字搜索网盘文件（百度接口为模糊搜索，后续再做精准过滤）"""
        all_items: List[dict] = []
        page = 1
        while True:
            params = {
                **self._base_params(),
                "method": "search",
                "dir": search_dir,
                "key": keyword,
                "recursion": "1" if recursive else "0",
                "page": str(page),
                "num": str(page_size),
            }
            resp = self.session.get(f"{PAN_API}/search", params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errno") != 0:
                raise RuntimeError(f"搜索失败: errno={data.get('errno')} {data.get('show_msg', '')}")

            items = data.get("list") or []
            if not items:
                break
            all_items.extend(items)
            if len(items) < page_size:
                break
            page += 1
        return all_items

    @staticmethod
    def exact_match(items: List[dict], filename: str) -> List[dict]:
        """精准匹配文件名（区分大小写）"""
        matched = []
        for item in items:
            if item.get("isdir", 0) == 1:
                continue
            name = item.get("server_filename") or item.get("filename") or ""
            if name == filename:
                matched.append(item)
        return matched

    @staticmethod
    def is_image_file(filename: str) -> bool:
        return Path(filename).suffix.lower() in IMAGE_EXTS

    def _user_id_str(self) -> str:
        if self._user_id:
            return str(self._user_id)
        try:
            resp = self.session.get(
                "https://pan.baidu.com/rest/2.0/membership/user",
                params={"method": "query", "app_id": "250528", "web": "5"},
                timeout=30,
            )
            data = resp.json()
            uid = data.get("user", {}).get("id") or data.get("login_info", {}).get("uid")
            if uid:
                self._user_id = int(uid)
                return str(self._user_id)
        except Exception:
            pass
        return ""

    def _get_dlink(self, remote_path: str) -> str:
        params = {**self._base_params(), "dlink": "1"}
        data = {"target": json.dumps([remote_path])}
        resp = self.session.post(
            f"{PAN_API}/filemetas",
            params=params,
            data=data,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("errno") != 0:
            raise RuntimeError(f"获取下载链接失败: errno={result.get('errno')}")

        info = result.get("info") or []
        if not info or info[0].get("errno", 0) != 0:
            raise RuntimeError(f"文件不存在或无权访问: {remote_path}")

        dlink = info[0].get("dlink")
        if not dlink:
            raise RuntimeError(f"未返回下载链接: {remote_path}")
        return dlink

    def _get_locatedownload_url(self, remote_path: str) -> Optional[str]:
        """通过安卓客户端 locatedownload 接口获取下载直链（更稳定）"""
        uid = self._user_id_str()
        devuid = hashlib.md5(self.bduss.encode()).hexdigest().upper() + "|0"
        enc = hashlib.sha1(self.bduss.encode()).hexdigest()
        timestamp = str(int(time.time()))
        rand_src = enc + uid + LOCATE_DOWNLOAD_KEY + timestamp + devuid
        rand_val = hashlib.sha1(rand_src.encode()).hexdigest()

        params = {
            "method": "locatedownload",
            "app_id": "250528",
            "path": remote_path,
            "ver": "4.0",
            "clienttype": "17",
            "channel": "0",
            "time": timestamp,
            "rand": rand_val,
            "devuid": devuid,
            "cuid": devuid,
            "apn_id": "1_0",
            "check_blue": "1",
            "es": "1",
            "esl": "1",
            "freeisp": "0",
            "queryfree": "0",
            "use": "0",
        }
        headers = {
            "User-Agent": PCS_UA,
            "Cookie": "; ".join(f"{k}={v}" for k, v in self.session.cookies.get_dict().items()),
        }
        resp = self.session.get(
            "https://pcs.baidu.com/rest/2.0/pcs/file",
            params=params,
            headers=headers,
            timeout=60,
        )
        if resp.status_code != 200:
            return None
        try:
            info = resp.json()
        except json.JSONDecodeError:
            return None
        if info.get("host") == "issuecdn.baidupcs.com":
            return None
        urls = info.get("urls") or []
        if not urls:
            return None
        return urls[0].get("url")

    def _stream_to_file(self, url: str, local_path: Path, extra_headers: Optional[dict] = None) -> None:
        last_error: Optional[Exception] = None
        for hdrs in DOWNLOAD_HEADER_SETS:
            headers = dict(hdrs)
            if extra_headers:
                headers.update(extra_headers)
            try:
                with self.session.get(
                    url,
                    headers=headers,
                    stream=True,
                    allow_redirects=True,
                    timeout=300,
                ) as resp:
                    if resp.status_code == 403:
                        last_error = requests.HTTPError(
                            f"403 Forbidden (UA: {headers.get('User-Agent', '')[:20]}…)"
                        )
                        continue
                    resp.raise_for_status()
                    if "wenxintishi" in resp.url:
                        raise RuntimeError(
                            "下载被限速或需要验证，请稍后重试或在浏览器中确认账号状态"
                        )
                    total = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    with open(local_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = downloaded * 100 // total
                                print(f"\r  下载进度: {pct}%", end="", flush=True)
                    if total > 0:
                        print()
                    return
            except requests.HTTPError as e:
                last_error = e
                continue
        if last_error:
            raise last_error
        raise RuntimeError("下载失败：所有下载方式均被拒绝")

    def download_file(self, remote_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []

        locate_url = self._get_locatedownload_url(remote_path)
        if locate_url:
            try:
                self._stream_to_file(
                    locate_url,
                    local_path,
                    extra_headers={"Cookie": f"BDUSS={self.bduss}"},
                )
                return
            except Exception as e:
                errors.append(f"locatedownload: {e}")

        try:
            dlink = self._get_dlink(remote_path)
            self._stream_to_file(dlink, local_path)
            return
        except Exception as e:
            errors.append(f"dlink: {e}")

        raise RuntimeError("；".join(errors) if errors else "下载失败")

    @staticmethod
    def _item_filename(item: dict) -> str:
        return item.get("server_filename") or item.get("filename") or ""

    def find_exact_image(
        self, filename: str, search_dir: str, recursive: bool
    ) -> tuple[Optional[dict], int]:
        """搜索并返回 (第一个匹配的图片, 匹配到的图片总数)

        - 带扩展名：按完整文件名精准匹配
        - 无扩展名（如 SFD202603072351）：按文件名主干匹配任意图片格式
        """
        items = self.search_files(filename, search_dir=search_dir, recursive=recursive)
        query = Path(filename)
        images: List[dict] = []

        if query.suffix.lower() in IMAGE_EXTS:
            matched = self.exact_match(items, filename)
            images = [m for m in matched if self.is_image_file(self._item_filename(m))]
        else:
            for item in items:
                if item.get("isdir", 0) == 1:
                    continue
                name = self._item_filename(item)
                if not self.is_image_file(name):
                    continue
                if Path(name).stem == filename:
                    images.append(item)

        if not images:
            return None, 0
        return images[0], len(images)
