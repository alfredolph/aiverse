"""在 github.com:443 被网络阻断、但 api.github.com 通的情况下，用 Git Data API 推送。

背景：某些网络环境会单独屏蔽 `github.com:443`，导致 `git push` 直接超时，
但 `api.github.com` / `codeload.github.com` / `uploads.github.com` 都是通的。
这时可以用 GitHub 的 Git Data API 手工「组装」一个 commit 并移动分支指针：

    取远端 HEAD → 为改动文件建 blob → 用 base_tree 建 tree
    → 建 commit → 把 refs/heads/<branch> 指过去

用法：
    python tools/gh_push_api.py                  # 推送当前分支到 origin
    python tools/gh_push_api.py --branch main
    python tools/gh_push_api.py --from HEAD~1    # 只推指定提交带来的改动
    python tools/gh_push_api.py --dry-run
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com"


def token() -> str:
    p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        print("  ✗ 拿不到 token，请先 python tools/gh_login.py")
        raise SystemExit(1)
    return p.stdout.strip()


def api(method: str, path: str, tok: str, payload: dict | None = None):
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AIVerse",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        print(f"  ✗ {method} {path} -> {e.code}\n    {detail}")
        raise SystemExit(1)


def git(*args: str) -> str:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)
    if p.returncode != 0:
        print(f"  ✗ git {' '.join(args)}\n    {p.stderr.strip()[:300]}")
        raise SystemExit(1)
    return p.stdout


def file_mode(path: str) -> str:
    """从本地 git 索引里读真实文件模式，避免把普通文件误标成可执行。"""
    p = subprocess.run(["git", "ls-tree", "HEAD", "--", path],
                       cwd=str(ROOT), capture_output=True, text=True)
    line = p.stdout.strip()
    if line:
        return line.split()[0]
    return "100644"


def repo_login(tok: str) -> str:
    return api("GET", "/user", tok)["login"]


def main() -> int:
    ap = argparse.ArgumentParser(description="用 Git Data API 推送（绕过 github.com:443 被墙）")
    ap.add_argument("--repo", default="aiverse", help="仓库名")
    ap.add_argument("--branch", default="", help="分支名（默认当前分支）")
    ap.add_argument("--from", dest="since", default="", help="只推该提交带来的改动（默认对比远端 HEAD）")
    ap.add_argument("--message", default="", help="提交信息（默认用本地 HEAD 的提交信息）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tok = token()
    owner = repo_login(tok)
    branch = args.branch or git("branch", "--show-current").strip() or "master"
    local_head = git("rev-parse", "HEAD").strip()
    print(f"\n  仓库   : {owner}/{args.repo}")
    print(f"  分支   : {branch}")
    print(f"  本地   : {local_head[:8]}")

    ref = api("GET", f"/repos/{owner}/{args.repo}/git/ref/heads/{branch}", tok)
    remote_head = ref["object"]["sha"]
    print(f"  远端   : {remote_head[:8]}")

    if remote_head == local_head:
        print("  · 远端已是最新，无需推送")
        return 0

    base = args.since or remote_head
    names = git("diff", "--name-status", base, local_head).strip().splitlines()
    if not names:
        print("  · 没有差异")
        return 0
    print(f"\n  待推送 {len(names)} 个文件：")
    for line in names:
        print("    " + line)

    if args.dry_run:
        print("\n  （--dry-run，未实际推送）")
        return 0

    # 1) 为每个文件建 blob
    print("\n[1/4] 上传文件内容（blob）")
    entries = []
    for line in names:
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        if status.startswith("D"):
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            print(f"  - 删除 {path}")
            continue
        raw = (ROOT / path).read_bytes()
        blob = api("POST", f"/repos/{owner}/{args.repo}/git/blobs", tok, {
            "content": base64.b64encode(raw).decode(),
            "encoding": "base64",
        })
        entries.append({"path": path, "mode": file_mode(path),
                        "type": "blob", "sha": blob["sha"]})
        print(f"  + {path}  {len(raw)} B")

    # 删除的文件要从 tree 里剔除：Git Data API 用 sha=null 表示删除
    # 2) 建 tree
    print("\n[2/4] 组装 tree")
    base_commit = api("GET", f"/repos/{owner}/{args.repo}/git/commits/{remote_head}", tok)
    tree = api("POST", f"/repos/{owner}/{args.repo}/git/trees", tok, {
        "base_tree": base_commit["tree"]["sha"],
        "tree": entries,
    })
    print(f"  tree {tree['sha'][:8]}")

    # 3) 建 commit
    print("\n[3/4] 创建 commit")
    msg = args.message or git("log", "-1", "--format=%B").strip()
    commit = api("POST", f"/repos/{owner}/{args.repo}/git/commits", tok, {
        "message": msg,
        "tree": tree["sha"],
        "parents": [remote_head],
    })
    print(f"  commit {commit['sha'][:8]}")

    # 4) 移动分支
    print("\n[4/4] 更新分支指针")
    api("PATCH", f"/repos/{owner}/{args.repo}/git/refs/heads/{branch}", tok,
        {"sha": commit["sha"], "force": False})
    print(f"  ✓ {branch} -> {commit['sha'][:8]}")

    # 本地也指过去，避免下次 git 状态错乱
    subprocess.run(["git", "update-ref", f"refs/heads/{branch}", commit["sha"]],
                   cwd=str(ROOT), capture_output=True)
    print(f"\n  https://github.com/{owner}/{args.repo}/commits/{branch}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
