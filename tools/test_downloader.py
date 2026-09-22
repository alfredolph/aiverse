"""用真实下载验证「一键部署」最关键的下载/解压环节。

`Downloader.fetch()` + `unzip()` 是一键部署的地基 —— 它们坏了，整个 30 GB 的
部署流程就全废，而这条路在开发机上通常从没真跑过（因为不会真去下 26 GB 模型）。

所以这里挑一个**体积可接受、且是部署计划里真实要用**的组件来实测：
`uv` 运行时管理器（约 41 MB），完整走一遍
    多镜像 → Range 断点续传 → 进度回调 → 解压 → strip_root → 落地校验

用法：
    python tools/test_downloader.py            # 真实下载（约 41 MB）
    python tools/test_downloader.py --skip-net # 只跑本地逻辑（不联网）
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.runtime import catalog                                  # noqa: E402
from backend.runtime.downloader import Cancelled, Downloader, human_size  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-net", action="store_true", help="不联网，只验证本地逻辑")
    args = ap.parse_args()

    fail: list[str] = []

    def need(cond, msg, label=""):
        print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
        if not cond:
            fail.append(msg)

    tmp = Path(tempfile.mkdtemp(prefix="aiverse_dl_"))
    print(f"\n临时目录：{tmp}")

    events: list[dict] = []
    dl = Downloader(progress=lambda d: events.append(d))

    # ---------------------------------------------------------- 断点续传
    print("\n[1/5] 来路不明的断点缓存必须被丢弃（而不是接着下）")
    dest = tmp / "uv.zip"
    part = dest.with_suffix(".zip.part")
    part.write_bytes(b"\x00" * (1024 * 1024))   # 假装已经下了 1 MB，但内容是垃圾
    print(f"     预置垃圾 .part = {human_size(part.stat().st_size)}（无 .meta 记录）")

    if args.skip_net:
        print("     （--skip-net，跳过真实下载）")
    else:
        urls = catalog.component_urls("uv", "cn")
        print(f"     候选镜像 {len(urls)} 个，首选：{urls[0][:70]}…")
        t0 = time.time()
        try:
            got = dl.fetch(urls, dest, label="uv 运行时管理器", expected_gb=0.04)
        except Exception as e:
            print(f"  ✗ 下载失败：{type(e).__name__}: {e}")
            print("     （可能是网络问题，不代表代码有问题）")
            return 1
        dt = time.time() - t0
        need(got.exists(), "下载后目标文件应存在")
        need(dest.stat().st_size > 5 * 1024 * 1024,
             f"uv.zip 体积异常：{dest.stat().st_size}",
             f"下载完成 {human_size(dest.stat().st_size)} · 耗时 {dt:.1f}s")
        need(not part.exists(), ".part 临时文件应被清理",
             ".part 临时文件已清理")

        phases = {e.get("phase") for e in events}
        need("retry" in phases,
             f"应提示「发现无记录断点、重新下载」，实际 phases={phases}",
             "检测到来路不明的断点缓存并主动丢弃（不会拼出坏文件）")
        need("download" in phases or "done" in phases,
             f"应触发进度回调，实际 phases={phases}",
             f"进度回调 {len(events)} 次")
        pcts = [e.get("percent") for e in events if e.get("percent")]
        need(bool(pcts) and max(pcts) > 50,
             f"进度百分比应有推进，实际 max={max(pcts) if pcts else None}",
             f"进度推进到 {max(pcts):.1f}%")
        speeds = [e.get("speed_mbps") for e in events if e.get("speed_mbps")]
        need(bool(speeds), "应报告下载速度",
             f"速度上报 {max(speeds):.1f} MB/s（峰值）" if speeds else "")

        # ---------------------------------------------------------- 真续传
        print("\n[2/5] 真正的续传：拿刚下好的文件截断一半，再续回来")
        half = dest.stat().st_size // 2
        data = dest.read_bytes()
        part.write_bytes(data[:half])
        meta = dest.with_suffix(".zip.part.meta")
        meta.write_text(json.dumps({"url": urls[0], "total": len(data)}), encoding="utf-8")
        dest.unlink()
        print(f"     截断到 {human_size(half)}，写入配套 .meta")
        try:
            dl.fetch(urls, dest, label="uv 续传", expected_gb=0.04)
            need(dest.stat().st_size == len(data),
                 f"续传后大小应为 {len(data)}，实际 {dest.stat().st_size}",
                 f"续传后大小与完整文件一致（{human_size(dest.stat().st_size)}）")
            need(dest.read_bytes() == data,
                 "续传结果与完整下载不一致（内容损坏！）",
                 "续传内容与原文件逐字节一致")
        except Exception as e:
            need(False, f"续传失败：{type(e).__name__}: {e}")

        # ---------------------------------------------------------- 解压
        print("\n[3/5] 解压 + strip_root（压缩包内多一层目录）")
        out = dl.unzip(dest, tmp / "uv")
        need(out.exists(), f"解压目标应存在：{out}")
        uv_exe = next((p for p in out.rglob("uv.exe")), None)
        need(uv_exe is not None, f"应能在解压结果里找到 uv.exe（实际 {out}）",
             f"找到 uv.exe：{uv_exe.relative_to(tmp) if uv_exe else '-'}")
        need(uv_exe is not None and (out / "uv.exe").exists(),
             "strip_root 后 uv.exe 应直接位于解压根目录",
             "strip_root 生效：uv.exe 在根目录")

        # ---------------------------------------------------------- 真能跑
        print("\n[4/5] 落地文件真的能执行")
        import subprocess
        r = subprocess.run([str(out / "uv.exe"), "--version"],
                           capture_output=True, text=True, timeout=60)
        need(r.returncode == 0, f"uv.exe 执行失败：{r.stderr[:200]}",
             f"uv --version → {(r.stdout or r.stderr).strip()}")

    # ---------------------------------------------------------- 取消
    print("\n[5/5] 取消机制")
    cancel_dl = Downloader(progress=None, is_cancelled=lambda: True)
    try:
        cancel_dl.fetch(["https://ghproxy.net/"], tmp / "should_not_exist.bin")
        need(False, "取消状态下 fetch 应该抛 Cancelled")
    except Cancelled:
        need(True, "", "is_cancelled=True 时正确抛出 Cancelled")
    except Exception as e:
        need(False, f"应抛 Cancelled，实际 {type(e).__name__}: {e}")

    # 清理
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "─" * 60)
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        return 1
    print("✓ 下载 / 断点续传 / 解压 / 进度 / 取消 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
