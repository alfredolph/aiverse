"""验证「FFmpeg 随程序自带」这条链路：找得到、认得出、不再重复下载。

FFmpeg 从 v1.0.6 起打进安装包 / exe，所以：
  1. 查找顺序必须是 runtime（部署装的）> 程序自带 > 系统 PATH；
  2. ffprobe 要能**独立**找到，而不是只在 ffmpeg 旁边找 ——
     早先 ffmpeg 命中自带那份时，装在 runtime 里的 ffprobe 就永远找不到了；
  3. 自带的那份能用时，部署计划里不该再排一次下载（白下 92 MB）。

全程本地，不联网、不真装 FFmpeg（用一个假 exe + 打桩的 `ffmpeg -version`）。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import config as cfg                     # noqa: E402
from backend.media import ffmpeg as ff                     # noqa: E402

fail: list[str] = []


def need(cond: bool, ok_msg: str, bad_msg: str = "") -> None:
    print(("  ✓ " + ok_msg) if cond else ("  ✗ " + (bad_msg or ok_msg)))
    if not cond:
        fail.append(bad_msg or ok_msg)


class _FakeCompleted:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.returncode = 0
        self.stderr = ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aiverse-ffmpeg-") as td:
        root = Path(td)
        fake_base = root / "app"                  # 假装这是 exe 所在目录
        fake_rt = root / "runtime"                # 假装这是一键部署的运行时目录

        old_base, old_rt = cfg.BASE_DIR, cfg.RUNTIME_DIR
        cfg.BASE_DIR, cfg.RUNTIME_DIR = fake_base, fake_rt
        try:
            print("\n[1/4] 一份都没有时：如实说没有")
            ff._DETECT_CACHE = None
            d = ff.detect(fresh=True)
            need(d["available"] is False or "runtime" not in str(d.get("path") or ""),
                 f"找不到时如实返回不可用（{d['hint'][:40]}）",
                 "一份都没有时应返回 available=False")

            print("\n[2/4] 自带的那份：要能被认出来")
            bundled_dir = fake_base / "ffmpeg" / "bin"
            bundled_dir.mkdir(parents=True)
            (bundled_dir / "ffmpeg.exe").write_bytes(b"fake")     # 只是让 exists() 为真
            ff._DETECT_CACHE = None

            real_run = subprocess.run
            ff.subprocess.run = (                                  # type: ignore[assignment]
                lambda *a, **k: _FakeCompleted("ffmpeg version 7.1 fake\n"))
            try:
                d = ff.detect(fresh=True)
            finally:
                ff.subprocess.run = real_run                       # type: ignore[assignment]
            need(d["available"] is True, f"自带的那份被识别为可用（{d['version'][:28]}）",
                 f"自带的那份应可用，实际 {d}")
            need(d["bundled"] is True, "bundled 标记为真", "bundled 应为 True")
            need(str(bundled_dir) in str(d["path"]), f"路径指向自带那份：{d['path']}",
                 f"路径不对：{d['path']}")

            print("\n[3/4] runtime 里后来又装了一份：应以 runtime 那一份为准")
            rt_dir = fake_rt / "ffmpeg" / "bin"
            rt_dir.mkdir(parents=True)
            (rt_dir / "ffmpeg.exe").write_bytes(b"fake")
            ff._DETECT_CACHE = None
            p = ff.ffmpeg_path()
            need(p is not None and "runtime" in str(p).lower(),
                 f"优先用 runtime 那份：{p}",
                 f"应以 runtime 那份为准，实际 {p}")
            ff._DETECT_CACHE = None
            real_run = subprocess.run
            ff.subprocess.run = (                                  # type: ignore[assignment]
                lambda *a, **k: _FakeCompleted("ffmpeg version 7.1 fake\n"))
            try:
                d2 = ff.detect(fresh=True)
            finally:
                ff.subprocess.run = real_run                       # type: ignore[assignment]
            need(d2["bundled"] is False, "runtime 那份的 bundled 标记为 False",
                 "runtime 那份是用户自己部署的，bundled 应为 False")

            print("\n[4/4] ffprobe 独立查找 + 部署计划不再重复下载")
            # ffprobe 只装在 runtime 里、ffmpeg 用的是自带那份 —— 这个组合
            # 在旧实现里会让 ffprobe 永远找不到。
            (rt_dir / "ffprobe.exe").write_bytes(b"fake")
            probe = ff.ffprobe_path()
            need(probe is not None and probe.name == "ffprobe.exe",
                 f"ffprobe 独立找到了：{probe}",
                 f"ffprobe 应能在 runtime 里独立找到，实际 {probe}")

            from backend.runtime import planner
            plan = planner.build_plan(mirror="cn")
            keys = [s["key"] for s in plan["steps"]]
            need("ffmpeg" not in keys,
                 "FFmpeg 已可用，部署计划里不再排下载它",
                 f"FFmpeg 已经能用了，计划里却还要下一次：{keys}")

            # 反过来：把自带的那份挪走，必须重新排上 —— 否则导出成片就没指望了
            (bundled_dir / "ffmpeg.exe").unlink()
            rt_only = root / "runtime2"
            cfg.RUNTIME_DIR = rt_only
            ff._DETECT_CACHE = None
            plan2 = planner.build_plan(mirror="cn")
            keys2 = [s["key"] for s in plan2["steps"]]
            need("ffmpeg" in keys2,
                 "FFmpeg 不可用时，部署计划里必须排上下载",
                 f"没有可用 FFmpeg 时计划里却没有它：{keys2}")
        finally:
            cfg.BASE_DIR, cfg.RUNTIME_DIR = old_base, old_rt

    print("\n" + ("─" * 62))
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("  · " + f)
        return 1
    print("✓ FFmpeg 自带链路全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
