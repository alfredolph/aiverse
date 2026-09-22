"""把 AIVerse 发布到 GitHub（授权完成后一条命令搞定）。

做四件事：
    1. 校验 gh 登录状态，读取账号信息
    2. 把 git user.name / user.email 设成该账号
    3. 提交当前全部改动
    4. 创建仓库（默认公开）并 push，可选打 tag 触发 CI 自动构建 exe

用法：
    python tools/gh_publish.py                 # 提交 + push，不打 tag
    python tools/gh_publish.py --tag v1.0.0    # 顺便打 tag，触发 GitHub Actions 出 Release
    python tools/gh_publish.py --private       # 建私有仓库
    python tools/gh_publish.py --repo my-name  # 指定仓库名（默认 aiverse）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GH = "gh"


def run(args: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(args, cwd=str(ROOT), text=True,
                       capture_output=True, **kw)
    if check and p.returncode != 0:
        print(f"  ✗ {' '.join(args)}\n    {p.stderr.strip()[:400]}")
        raise SystemExit(1)
    return p


def gh_json(args: list[str]) -> dict:
    p = run([GH] + args)
    return json.loads(p.stdout or "{}")


def main() -> int:
    ap = argparse.ArgumentParser(description="发布 AIVerse 到 GitHub")
    ap.add_argument("--repo", default="aiverse", help="仓库名（默认 aiverse）")
    ap.add_argument("--tag", default="", help="打 tag 并推送，触发 CI 构建 Release")
    ap.add_argument("--private", action="store_true", help="创建私有仓库")
    ap.add_argument("--message", default="", help="提交信息（默认自动生成）")
    args = ap.parse_args()

    print("\n[1/4] 校验 GitHub 登录状态")
    st = run([GH, "auth", "status"], check=False)
    if st.returncode != 0:
        print("  ✗ 尚未登录。请先运行：python tools/gh_login.py")
        print("    （它会给出一个设备码，到 https://github.com/login/device 输入即可）")
        return 1
    me = gh_json(["api", "user"])
    login = me.get("login")
    print(f"  ✓ 已登录：{login}")

    print("\n[2/4] 设置 git 身份")
    email = me.get("email") or f"{login}@users.noreply.github.com"
    run(["git", "config", "user.name", login])
    run(["git", "config", "user.email", email])
    print(f"  ✓ {login} <{email}>")

    print("\n[3/4] 提交改动")
    run(["git", "add", "-A"])
    dirty = run(["git", "status", "--porcelain"], check=False).stdout.strip()
    if dirty:
        n = len([l for l in dirty.splitlines() if l.strip()])
        msg = args.message or f"feat: 一键部署本地 H3 推理环境 + 离线包分发（{n} 项变更）"
        run(["git", "commit", "-m", msg])
        print(f"  ✓ 已提交 {n} 项变更")
    else:
        print("  · 工作区干净，无需提交")

    print("\n[4/4] 创建仓库并推送")
    has_remote = run(["git", "remote", "get-url", "origin"], check=False).returncode == 0
    if not has_remote:
        vis = "--private" if args.private else "--public"
        run([GH, "repo", "create", args.repo, vis,
             "--source", ".", "--remote", "origin",
             "--description", "AI 漫剧一键生产客户端 · 8 阶段管线 + 强制审核门 + 抽卡 + 一键部署本地 MiniMax H3"])
        print(f"  ✓ 已创建仓库 {login}/{args.repo}（{'私有' if args.private else '公开'}）")
    else:
        print("  · 已存在 origin，跳过创建")

    branch = run(["git", "branch", "--show-current"], check=False).stdout.strip() or "main"
    run(["git", "push", "-u", "origin", branch])
    print(f"  ✓ 已推送分支 {branch}")

    if args.tag:
        run(["git", "tag", args.tag])
        run(["git", "push", "origin", args.tag])
        print(f"  ✓ 已推送 tag {args.tag} —— GitHub Actions 会自动构建 exe 并挂到 Release")
        print(f"    进度：https://github.com/{login}/{args.repo}/actions")

    print(f"\n  仓库地址：https://github.com/{login}/{args.repo}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
