"""GitHub OAuth 设备码登录助手。

不依赖 gh CLI 的交互式提示，全自动完成：
    1. 申请设备码（或复用已有的）
    2. 轮询等待用户在浏览器中授权
    3. 拿到 token 后写入 gh CLI 凭据 + 打印账号信息

用法：
    python tools/gh_login.py                 # 生成新设备码并等待授权
    python tools/gh_login.py <device_code>   # 复用已有的设备码
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT_ID = "178c6fc778ccc68e1d6a"  # GitHub CLI 官方 OAuth App
SCOPES = "repo read:org workflow"
ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".gh_token"


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AIVerse",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def request_code() -> dict:
    return post("https://github.com/login/device/code",
                {"client_id": CLIENT_ID, "scope": SCOPES})


def poll_once(device_code: str) -> tuple[str, str]:
    """返回 (state, token)。state ∈ pending|slow_down|ok|error"""
    d = post("https://github.com/login/oauth/access_token",
             {"client_id": CLIENT_ID, "device_code": device_code,
              "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if "access_token" in d:
        return "ok", d["access_token"]
    err = d.get("error", "")
    if err == "authorization_pending":
        return "pending", ""
    if err == "slow_down":
        return "slow_down", ""
    return "error", d.get("error_description", err)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        device_code = args[0]
        print("  复用设备码，等待授权中…")
    else:
        d = request_code()
        device_code = d["device_code"]
        print("\n" + "=" * 62)
        print("  请打开浏览器访问： " + d["verification_uri"])
        print("  并输入一次性代码： " + d["user_code"])
        print("=" * 62 + "\n")

    interval = 5
    deadline = time.time() + 880
    while time.time() < deadline:
        state, value = poll_once(device_code)
        if state == "ok":
            token = value
            TOKEN_FILE.write_text(token, encoding="utf-8")
            try:
                me = get("https://api.github.com/user", token)
                print(f"  ✓ 登录成功：{me.get('login')} ({me.get('name') or ''})")
                print(f"    邮箱：{me.get('email') or '（私有，用 noreply 地址）'}")
                Path(ROOT / ".gh_login").write_text(me.get("login", ""), encoding="utf-8")
            except Exception as e:
                print(f"  ✓ 已获取 token（查询账号失败：{e}）")
            # 写入 gh CLI 凭据
            try:
                p = subprocess.run(["gh", "auth", "login", "--with-token"],
                                   input=token, text=True, capture_output=True, timeout=60)
                print("  gh auth login:", "OK" if p.returncode == 0 else p.stderr.strip()[:200])
            except FileNotFoundError:
                print("  （未找到 gh CLI，token 已保存到 .gh_token）")
            return 0
        if state == "slow_down":
            interval = min(interval + 5, 30)
        elif state == "error":
            print(f"  ✗ 授权失败：{value}")
            return 1
        time.sleep(interval)
    print("  ✗ 超时未授权")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
