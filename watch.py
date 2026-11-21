"""TikTok 新作品监控（用 yt-dlp 抓取，GitHub Actions 定时运行）。

环境变量：
  - TIKTOK_COOKIE（可选）：登录后的 Cookie 字符串；有就加上，能降低被风控的概率
  - SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / MAIL_TO：发信配置

文件：
  - creators.txt：每行一个博主用户名（不带 @）
  - state.json：记录每个博主上次看到的视频 ID
"""

from __future__ import annotations

import json
import os
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "state.json"
CREATORS_FILE = BASE / "creators.txt"

COOKIE = os.environ.get("TIKTOK_COOKIE", "").strip()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
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
    for line in CREATORS_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.lstrip("@"))
    return names


def ensure_ytdlp() -> None:
    """确保 yt-dlp 可用；Actions 里若不预装，则自动安装。"""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("安装 yt-dlp ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "yt-dlp"],
            check=True,
        )


def latest_video(user: str) -> tuple[str, str] | None:
    """返回 (视频ID, 标题)；失败返回 None。"""
    url = f"https://www.tiktok.com/@{user}"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--playlist-end",
        "1",
        "--no-warnings",
        "--ignore-errors",
        "--print",
        "%(id)s\t%(title)s",
    ]
    if COOKIE:
        cmd += ["--add-header", f"Cookie: {COOKIE}"]
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] {user}: yt-dlp 超时", file=sys.stderr)
        return None

    out = (proc.stdout or "").strip()
    if not out:
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-1] if err else "无输出"
        print(f"[WARN] {user}: 未获取到视频（{tail}）", file=sys.stderr)
        return None

    first = out.splitlines()[0]
    parts = first.split("\t", 1)
    vid = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else ""
    if not vid or not vid.isdigit():
        print(f"[WARN] {user}: 解析到无效 ID: {first[:80]}", file=sys.stderr)
        return None
    return vid, title


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
    ensure_ytdlp()
    creators = load_creators()
    if not creators:
        print("creators.txt 为空", file=sys.stderr)
        return 2

    state = load_state()
    failures = 0

    for user in creators:
        result = latest_video(user)
        if result is None:
            failures += 1
            continue
        vid, title = result

        last_id = state.get(user, {}).get("last_id")
        if last_id != vid:
            state[user] = {"last_id": vid, "title": title}
            if last_id is not None:
                url = f"https://www.tiktok.com/@{user}/video/{vid}"
                body = f"博主：@{user}\n视频：{url}\n标题：{title or '(无)'}\n"
                send_email(f"TikTok 新作品：@{user}", body)
                print(f"[NEW] {user}: {url}")
            else:
                print(f"[INIT] {user}: {vid}")
        else:
            print(f"[SAME] {user}: {vid}")

    save_state(state)
    print(f"完成，失败 {failures} 个")
    return 1 if failures and failures == len(creators) else 0


if __name__ == "__main__":
    raise SystemExit(main())
