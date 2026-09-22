"""用真实组件端到端跑一遍「部署器本体」。

为什么需要它：`tools/test_downloader.py` 只测了下载器这一个零件，
而 `Installer._run()` 才是把整条路串起来的东西 ——
    计划 → 逐步执行 → 下载 → 解压 → 落地 → 状态持久化 → 失败重试 → 幂等跳过
这条路在开发机上从来没真跑过，因为完整计划要下 30 GB。

这里挑计划里体积较小的 `download_zip` 步骤真跑（uv 17 MB + FFmpeg 92 MB）：
    _run() 全程 → 两个 exe 真执行 → state.json 内容 → status() → 幂等重跑

`--with-comfyui` 会再加两步：ComfyUI 源码包（约 30 MB）与 KJNodes（约 5 MB）。
为什么专门测它俩：ComfyUI 以前是用 comfy-cli 装的，而它的 `install` 其实只认
`--skip-manager`，`--nvidia` / `--yes` / `install --workspace` 这几个写法官方文档里
都没有，`node install <github-url>` 也无效（要的是 Registry ID）—— 也就是说那一步
大概率一跑就挂。改成直接下源码 zip 之后，落点对不对必须有个测试盯着。

torch / H3 权重那几步要 N 卡加几十 GB，不在本测试范围内。

用法：
    python tools/test_deploy_slice.py                # 含 FFmpeg（约 110 MB）
    python tools/test_deploy_slice.py --skip-ffmpeg  # 只跑 uv（约 17 MB）
    python tools/test_deploy_slice.py --with-comfyui # 再加 ComfyUI + KJNodes（约 145 MB）

注意：脚本会自己起一个子进程、把 AIVERSE_RUNTIME 指到临时目录再跑，
绝不会碰你本机已经部署好的 runtime/。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MARKER = "--in-child"


def run_child(tmp: str, skip_ffmpeg: bool, with_comfyui: bool) -> int:
    """子进程里跑真正的部署，确保 AIVERSE_RUNTIME 在 import 之前就生效。"""
    env = dict(os.environ)
    env["AIVERSE_RUNTIME"] = tmp
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, "-u", str(Path(__file__).resolve()), MARKER,
           "--runtime", tmp]
    if skip_ffmpeg:
        cmd.append("--skip-ffmpeg")
    if with_comfyui:
        cmd.append("--with-comfyui")
    return subprocess.run(cmd, env=env).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ffmpeg", action="store_true", help="只跑 uv（约 17 MB）")
    ap.add_argument("--with-comfyui", action="store_true",
                    help="再加 ComfyUI 源码包与 KJNodes（约 35 MB）")
    ap.add_argument("--runtime", default="", help=argparse.SUPPRESS)
    ap.add_argument(MARKER, dest="in_child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # ---------------------------------------------------------- 父进程
    if not args.in_child:
        tmp = tempfile.mkdtemp(prefix="aiverse_deploy_")
        print(f"\n临时运行时目录：{tmp}")
        print("（不会碰你本机已有的 runtime/）")
        rc = run_child(tmp, args.skip_ffmpeg, args.with_comfyui)
        shutil.rmtree(tmp, ignore_errors=True)
        return rc

    # ---------------------------------------------------------- 子进程
    from backend.core.console import setup_console
    setup_console()

    from backend.runtime import catalog, planner
    from backend.runtime.installer import installer

    fail: list[str] = []

    def need(cond, msg, label=""):
        print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
        if not cond:
            fail.append(msg)

    rt = Path(args.runtime)
    print(f"\nRUNTIME_DIR = {rt}")
    print(f"state 文件   = {rt / 'state.json'}")

    # ------------------------------------------------------ [1/5] 计划过滤
    print("\n[1/5] 从真实部署计划里挑出 download_zip 步骤")
    plan = planner.build_plan(mirror="cn", include_nodes=args.with_comfyui)
    want = {"uv"}
    if not args.skip_ffmpeg:
        want.add("ffmpeg")
    if args.with_comfyui:
        want |= {"comfyui", "kj-nodes"}
    steps = [s for s in plan["steps"] if s["key"] in want]
    got = {s["key"] for s in steps}
    need(got == want, f"计划里应有 {want}，实际 {got}", f"取到步骤：{sorted(got)}")
    total_gb = sum(s.get("size_gb", 0) for s in steps)
    plan = dict(plan, steps=steps,
                total_download_human=f"{total_gb * 1024:.0f} MB")
    print(f"     预计下载约 {total_gb * 1024:.0f} MB")

    # ------------------------------------------------------ [2/5] 真跑
    print("\n[2/5] 执行 Installer._run()（真实下载 + 解压 + 落地）")
    t0 = time.time()
    installer()._run(plan)
    dt = time.time() - t0
    st = installer().status()
    need(st["status"] == "done",
         f"部署应成功，实际 status={st['status']} error={st.get('error')}",
         f"部署成功，耗时 {dt:.0f}s")
    if st["status"] != "done":
        print("\n" + "─" * 60)
        for line in (st.get("log") or [])[-10:]:
            print("   " + line)
        return 1

    for s in steps:
        info = st["steps"].get(s["key"], {})
        need(info.get("status") == "done" and info.get("percent") == 100.0,
             f"{s['key']} 步骤状态应为 done/100，实际 {info.get('status')}/{info.get('percent')}",
             f"{s['key']} 步骤 done，{info.get('message')}")

    # ------------------------------------------------------ [3/5] 落地验证
    print("\n[3/5] 落地文件真的能跑")
    uv_exe = rt / "uv" / "uv.exe"
    need(uv_exe.exists(), f"应有 {uv_exe}", "uv.exe 已就位")
    if uv_exe.exists():
        r = subprocess.run([str(uv_exe), "--version"], capture_output=True,
                           text=True, timeout=90)
        need(r.returncode == 0, f"uv --version 失败：{(r.stderr or '')[:200]}",
             f"uv --version → {(r.stdout or r.stderr).strip()}")

    if not args.skip_ffmpeg:
        ff = rt / "ffmpeg" / "bin" / "ffmpeg.exe"
        need(ff.exists(), f"应有 {ff}", "ffmpeg.exe 已就位")
        if ff.exists():
            r = subprocess.run([str(ff), "-version"], capture_output=True,
                               text=True, timeout=90)
            first = (r.stdout or r.stderr).strip().splitlines()
            need(r.returncode == 0, f"ffmpeg -version 失败：{(r.stderr or '')[:200]}",
                 f"ffmpeg -version → {first[0][:70] if first else '?'}")

    if args.with_comfyui:
        main_py = rt / "comfyui" / "main.py"
        need(main_py.exists(), f"应有 {main_py}（源码包解压落点错了？）",
             f"ComfyUI 本体已就位（{main_py.stat().st_size if main_py.exists() else 0} B）")
        req = rt / "comfyui" / "requirements.txt"
        need(req.exists(), f"应有 {req}（comfyui-deps 步骤要用它）",
             "ComfyUI requirements.txt 已就位")
        if req.exists():
            txt = req.read_text(encoding="utf-8", errors="replace")
            need("comfyui-frontend-package" in txt,
                 "requirements.txt 里没看到前端包，可能下到了别的分支",
                 "requirements.txt 含 comfyui-frontend-package（前端界面）")
        kj = rt / "comfyui" / "custom_nodes" / "ComfyUI-KJNodes" / "__init__.py"
        need(kj.exists(), f"应有 {kj}（多剥了一层目录？）",
             "KJNodes 已落到 custom_nodes/ComfyUI-KJNodes/")
        need(not list((rt / "comfyui" / "custom_nodes").glob("*-main")),
             "custom_nodes 下留了 ComfyUI-KJNodes-main 这种带分支名的目录",
             "custom_nodes 下没有多余的分支名目录（strip_root 正确）")

    leftovers = list((rt / "cache").glob("*.zip")) if (rt / "cache").exists() else []
    need(not leftovers, f"cache 里不该留压缩包，实际 {leftovers}",
         "cache 已清理，没留压缩包")

    # ------------------------------------------------------ [4/5] 状态持久化
    print("\n[4/5] 状态落盘（关掉程序再打开能接着看）")
    sf = rt / "state.json"
    need(sf.exists(), f"应有 {sf}", "state.json 已生成")
    if sf.exists():
        disk = json.loads(sf.read_text(encoding="utf-8"))
        need(disk.get("status") == "done",
             f"state.json 里 status 应为 done，实际 {disk.get('status')}",
             "state.json 记录 status=done")
        need(all(disk.get("steps", {}).get(k, {}).get("status") == "done"
                 for k in want),
             f"state.json 里步骤状态不对：{disk.get('steps')}",
             f"state.json 里 {len(want)} 个步骤都是 done")
        need(bool(disk.get("finished_at")), "state.json 应记录 finished_at",
             "state.json 记录了结束时间")

    inst = installer().detect_installed()
    need(inst.get("uv") and (args.skip_ffmpeg or inst.get("ffmpeg"))
         and (not args.with_comfyui or inst.get("comfyui")),
         f"detect_installed 应认出已装组件，实际 {inst}",
         f"detect_installed 认出：uv={inst.get('uv')} ffmpeg={inst.get('ffmpeg')} "
         f"comfyui={inst.get('comfyui')}")

    # ------------------------------------------------------ [5/5] 幂等
    print("\n[5/5] 幂等：再跑一遍应该全部跳过，不重复下载")
    t0 = time.time()
    installer()._run(plan)
    dt2 = time.time() - t0
    st2 = installer().status()
    skipped = [k for k in want
               if "跳过" in (st2["steps"].get(k, {}).get("message") or "")]
    need(len(skipped) == len(want),
         f"{len(want)} 个步骤都应报「已存在，跳过」，实际 {st2['steps']}",
         f"全部跳过，耗时 {dt2:.1f}s（首次 {dt:.0f}s）")
    need(dt2 < max(5.0, dt * 0.2),
         f"跳过应该很快，实际 {dt2:.1f}s（首次 {dt:.0f}s）",
         f"跳过耗时 {dt2:.1f}s，没有再下载")

    print("\n" + "─" * 60)
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        return 1
    print("✓ 部署器本体端到端通过（真实下载 + 解压 + 落地 + 执行 + 状态 + 幂等）")
    print("  完整计划里的 torch / H3 权重需要 N 卡与几十 GB，走的是同一套 _run 逻辑。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
