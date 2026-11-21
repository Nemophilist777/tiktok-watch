"""TikTok 新作品监控：GitHub Actions 定时运行，发现新视频就发邮件。

依赖：
  - 环境变量 TIKTOK_COOKIE：登录 tiktok.com 后从浏览器复制的 Cookie 字符串（必需）
  - SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / MAIL_TO：发信配置
  - creators.txt：每行一个博主用户名（不带 @）
  - state.json：记录每个博主上次看到的视频 ID（脚本自动维护）

策略：
  1. 用 Cookie 请求博主主页 HTML，提取 secUid；
  2. 调用 TikTok web API item_list 拿最新视频；
  3. 与 state.json 中的 last_id 比较，不同则发邮件；
  4. 支持 HTML 解析兜底（API 失败时尝试从 __UNIVERSAL_DATA_FOR_REHYDRATION__ 取）。

注意：TikTok 对数据中心 IP 风控较严，GitHub Actions 可能被拦截。
如果连续失败，考虑改用第三方 API 或降低频率。
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import requests

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "state.json"
CREATORS_FILE = BASE / "creators.txt"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)

COOKIE = os.environ.get("TIKTOK_COOKIE", "").strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_creators() -> list[str]:
    if not CREATORS_FILE.exists():
        return []
    names = []
    for line in CREATORS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.lstrip("@"))
    return names


def headers() -> dict:
    h = {
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.tiktok.com/",
    }
    if COOKIE:
        h["Cookie"] = COOKIE
    return h


def fetch_profile_html(user: str) -> str:
    url = f"https://www.tiktok.com/@{quote(user)}?lang=en"
    r = requests.get(url, headers=headers(), timeout=30)
    r.raise_for_status()
    return r.text


def extract_sec_uid(html: str) -> str | None:
    m = re.search(r'"secUid"\s*:\s*"([^"]+)"', html)
    return m.group(1) if m else None


def fetch_latest_api(user: str, sec_uid: str) -> dict | None:
    url = (
        "https://www.tiktok.com/api/post/item_list/"
        f"?aid=1988&count=5&secUid={sec_uid}"
        "&cursor=0&app_language=en&app_name=tiktok_web"
        "&browser_language=en-US&browser_platform=Win32"
        "&browser_name=Mozilla&browser_version=5.0"
        "&channel=tiktok_web&device_platform=web_pc"
        "&os=windows&priority_region=&region=US"
        "&screen_height=1080&screen_width=1920"
    )
    r = requests.get(url, headers=headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("itemList") or []
    if not items:
        return None
    item = items[0]
    vid = item.get("id") or item.get("aweme_id")
    author = (item.get("author") or {}).get("uniqueId", user)
    desc = (item.get("desc") or "").strip()
    create_time = item.get("createTime")
    return {
        "id": str(vid),
        "author": author,
        "desc": desc,
        "create_time": create_time,
        "url": f"https://www.tiktok.com/@{author}/video/{vid}",
    }


def fetch_latest_html_fallback(html: str, user: str) -> dict | None:
    """API 失败时，从页面内嵌 JSON 里找 itemList。"""
    m = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.S,
    )
    if not m:
        return None
    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    def walk(node, depth=0):
        if depth > 12:
            return None
        if isinstance(node, dict):
            if "itemList" in node and isinstance(node["itemList"], list):
                return node["itemList"]
            for v in node.values():
                found = walk(v, depth + 1)
                if found:
                    return found
        elif isinstance(node, list):
            for v in node:
                found = walk(v, depth + 1)
                if found:
                    return found
        return None

    items = walk(blob) or []
    if not items:
        return None
    item = items[0]
    vid = item.get("id") or item.get("aweme_id")
    if not vid:
        return None
    author = (item.get("author") or {}).get("uniqueId", user)
    return {
        "id": str(vid),
        "author": author,
        "desc": (item.get("desc") or "").strip(),
        "create_time": item.get("createTime"),
        "url": f"https://www.tiktok.com/@{author}/video/{vid}",
    }


def send_email(subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["MAIL_TO"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)


def main() -> int:
    if not COOKIE:
        print("缺少 TIKTOK_COOKIE 环境变量", file=sys.stderr)
        return 2

    creators = load_creators()
    if not creators:
        print("creators.txt 为空", file=sys.stderr)
        return 2

    state = load_state()
    failures = 0

    for user in creators:
        try:
            html = fetch_profile_html(user)
            sec_uid = extract_sec_uid(html)

            latest = None
            if sec_uid:
                latest = fetch_latest_api(user, sec_uid)
            if latest is None:
                latest = fetch_latest_html_fallback(html, user)

            if latest is None:
                print(f"[WARN] {user}: 未解析到最新视频")
                failures += 1
                continue

            last_id = state.get(user, {}).get("last_id")
            if last_id != latest["id"]:
                state[user] = {"last_id": latest["id"]}
                if last_id is not None:
                    subject = f"TikTok 新作品：@{latest['author']}"
                    body = (
                        f"博主：@{latest['author']}\n"
                        f"视频：{latest['url']}\n"
                        f"简介：{latest['desc'] or '(无)'}\n"
                    )
                    send_email(subject, body)
                    print(f"[NEW] {user}: {latest['url']}")
                else:
                    print(f"[INIT] {user}: 首次记录 {latest['id']}")
            else:
                print(f"[SAME] {user}: {latest['id']}")

            time.sleep(1.5)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[ERROR] {user}: {exc}", file=sys.stderr)

    save_state(state)
    print(f"完成，失败 {failures} 个")
    return 1 if failures and failures == len(creators) else 0


if __name__ == "__main__":
    raise SystemExit(main())
