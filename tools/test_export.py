"""端到端验证「剪辑导出」—— 真的产出一个能播的 MP4。

为什么需要它：导出是整条产线的最后一公里，也是最容易被跳过的部分 ——
没有 N 卡就没有真实镜头，于是 `run_export()` 永远走「只返回计划」那条分支，
真正拼视频的代码（concat + scale/pad + 烧字幕 + libx264/aac）从来没被执行过。

这里用 ffmpeg 自己合成三段 1 秒测试片段当作「已渲染镜头」，
再走一遍完整导出，最后用 ffprobe 校验产物：
    分辨率对不对 / 时长对不对 / 有没有音视频轨 / 是不是真的能解码

覆盖到的分支：
  * 有 ffmpeg + 有镜头 → 真渲染出 MP4
  * 有 ffmpeg + 没镜头 → 不崩，返回可读提示
  * 字幕烧录（subtitles 滤镜）
  * 9:16 竖屏的 scale/pad 到 1080x1920

用法：
    python tools/test_export.py                 # 需要 ffmpeg
    python tools/test_export.py --ffmpeg <path> # 指定 ffmpeg

脚本会起子进程把 AIVERSE_RUNTIME / AIVERSE_DATA 指到临时目录，
不会碰你本机的 runtime/ 与项目数据。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MARKER = "--in-child"
CLIPS = [
    ("clip1", "testsrc2=size=448x832:rate=24:duration=1", "440"),
    ("clip2", "smptebars=size=448x832:rate=24:duration=1", "554"),
    ("clip3", "testsrc=size=448x832:rate=24:duration=1", "659"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", default="", help="指定 ffmpeg 可执行文件")
    ap.add_argument("--runtime", default="", help=argparse.SUPPRESS)
    ap.add_argument("--data", default="", help=argparse.SUPPRESS)
    ap.add_argument(MARKER, dest="in_child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # ---------------------------------------------------------- 父进程
    if not args.in_child:
        tmp = Path(tempfile.mkdtemp(prefix="aiverse_export_"))
        rt = tmp / "runtime"
        data = tmp / "data"
        rt.mkdir(parents=True)
        data.mkdir(parents=True)
        env = dict(os.environ)
        env["AIVERSE_RUNTIME"] = str(rt)
        env["AIVERSE_DATA"] = str(data)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [sys.executable, "-u", str(Path(__file__).resolve()), MARKER,
               "--runtime", str(rt), "--data", str(data)]
        if args.ffmpeg:
            cmd += ["--ffmpeg", args.ffmpeg]
        print(f"\n临时目录：{tmp}")
        rc = subprocess.run(cmd, env=env).returncode
        shutil.rmtree(tmp, ignore_errors=True)
        return rc

    # ---------------------------------------------------------- 子进程
    from backend.core.console import setup_console
    setup_console()

    from backend.core import store
    from backend.media import ffmpeg

    fail: list[str] = []

    def need(cond, msg, label=""):
        print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
        if not cond:
            fail.append(msg)

    # ------------------------------------------------------ [1/6] 找 ffmpeg
    print("\n[1/6] 定位 FFmpeg")
    if args.ffmpeg:
        p = Path(args.ffmpeg)
        if p.exists():
            # 塞进 runtime，让 ffmpeg_path() 能认出来（模拟一键部署装好的那份）
            dest_dir = Path(args.runtime) / "ffmpeg" / "bin"
            dest_dir.mkdir(parents=True, exist_ok=True)
            for name in ("ffmpeg.exe", "ffprobe.exe"):
                src = p.with_name(name)
                if src.exists():
                    shutil.copy2(src, dest_dir / name)

    info = ffmpeg.detect()
    if not info["available"] and not args.ffmpeg:
        # 本机没有就直接用部署器装一份到临时 runtime —— 既省得手工准备，
        # 也顺带再走一遍用户真实走的那条安装路。
        print("     本机没有 ffmpeg，用部署器装一份到临时 runtime（约 92 MB）…")
        from backend.runtime import planner
        from backend.runtime.installer import installer
        full = planner.build_plan(mirror="cn")
        steps = [s for s in full["steps"] if s["key"] == "ffmpeg"]
        installer()._run(dict(full, steps=steps, total_download_human="92 MB"))
        info = ffmpeg.detect()

    need(info["available"], f"没有可用的 ffmpeg：{info['hint']}",
         f"ffmpeg 可用：{info['version']}")
    if not info["available"]:
        print("\n提示：先跑 `python tools/test_deploy_slice.py` 装上 ffmpeg，"
              "或用 --ffmpeg 指定路径。")
        return 1
    if info.get("bundled"):
        print("     （用的是 runtime/ 里那份，和用户一键部署后走的是同一条路）")

    # ------------------------------------------------------ [2/6] 造镜头
    print("\n[2/6] 用 ffmpeg 合成三段测试片段，当作「已渲染镜头」")
    pid = "p_test_export"
    base = store.ensure_dirs(pid, "导出测试")
    project = {"id": pid, "name": "导出测试", "aspect": "9:16"}
    shots: list[dict] = []
    for i, (name, src, freq) in enumerate(CLIPS, start=1):
        rel = f"shots/{name}.mp4"
        out = base / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [str(ffmpeg.ffmpeg_path()), "-y",
               "-f", "lavfi", "-i", src,
               "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=1",
               "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="ignore")
        need(r.returncode == 0 and out.exists(),
             f"合成 {name}.mp4 失败：{(r.stderr or '')[-200:]}",
             f"{name}.mp4 已生成（{out.stat().st_size / 1024:.0f} KB）" if out.exists() else "")
        shots.append({"id": f"s{i}", "index": i, "payload": {"video": {"video": rel}}})

    # 字幕：验证 subtitles 滤镜真的被挂上
    srt = base / "subtitles" / "subtitle.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:00,900\n第一镜：导出测试\n\n"
        "2\n00:00:01,000 --> 00:00:01,900\n第二镜：字幕烧录\n\n"
        "3\n00:00:02,000 --> 00:00:02,900\n第三镜：完成\n\n",
        encoding="utf-8")
    print(f"     字幕：{srt.relative_to(base)}")

    # ------------------------------------------------------ [3/6] 导出计划
    print("\n[3/6] 构建导出计划")
    opts = {"container": "MP4", "resolution": "1080p", "aspect": "9:16", "fps": 24}
    plan = ffmpeg.build_export_plan(project, shots, opts)
    need(plan["video_files"] == 3,
         f"应认出 3 个镜头，实际 {plan['video_files']}",
         f"认出 {plan['video_files']} 个镜头，输出尺寸 {plan['output_size']}")
    need(plan["output_size"] == "1080x1920",
         f"9:16 的 1080p 应为 1080x1920，实际 {plan['output_size']}",
         f"9:16 竖屏尺寸正确：{plan['output_size']}")
    need(plan["subtitle"] is not None,
         f"应识别到字幕，实际 {plan['subtitle']}",
         f"字幕已挂上：{plan['subtitle']}")
    concat = (base / plan["concat"]).read_text(encoding="utf-8")
    need(concat.count("file '") == 3,
         f"concat 清单应有 3 行 file，实际：{concat[:200]}",
         "concat 清单写了 3 个镜头")

    # ------------------------------------------------------ [4/6] 真渲染
    print("\n[4/6] 真正执行导出（concat + scale/pad + 烧字幕 + libx264/aac）")
    result = ffmpeg.run_export(project, shots, opts)
    need(result.get("rendered") is True,
         f"导出应成功，实际 message={result.get('message')}",
         f"导出完成：{result.get('output')}（{result.get('output_size_human')}）")
    out_file = base / (result.get("output") or "nope")
    need(out_file.exists() and out_file.stat().st_size > 1024,
         f"产物不存在或过小：{out_file}",
         f"产物 {out_file.name}，{out_file.stat().st_size / 1024:.0f} KB"
         if out_file.exists() else "")

    # ------------------------------------------------------ [5/6] ffprobe 校验
    print("\n[5/6] 用 ffprobe 校验产物是不是真能播")
    probe = ffmpeg.ffprobe_path()
    need(probe is not None, "找不到 ffprobe", "ffprobe 可用")
    if probe and out_file.exists():
        r = subprocess.run(
            [str(probe), "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(out_file)],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="ignore")
        import json
        meta = json.loads(r.stdout or "{}")
        streams = meta.get("streams", [])
        kinds = {s.get("codec_type") for s in streams}
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        dur = float(meta.get("format", {}).get("duration") or 0)

        need(r.returncode == 0 and bool(streams),
             f"ffprobe 读不出来：{(r.stderr or '')[:200]}",
             f"ffprobe 解析出 {len(streams)} 条流")
        need("video" in kinds, f"应有视频轨，实际 {kinds}", "有视频轨")
        need("audio" in kinds, f"应有音频轨，实际 {kinds}", "有音频轨")
        need((v.get("width"), v.get("height")) == (1080, 1920),
             f"分辨率应为 1080x1920，实际 {v.get('width')}x{v.get('height')}",
             f"分辨率 {v.get('width')}x{v.get('height')}")
        need(2.5 <= dur <= 3.6,
             f"时长应约 3 秒（3 段各 1 秒），实际 {dur:.2f}s",
             f"时长 {dur:.2f}s（3 段各 1 秒拼接正确）")
        need(v.get("codec_name") == "h264",
             f"编码应为 h264，实际 {v.get('codec_name')}",
             f"编码 {v.get('codec_name')} / {v.get('pix_fmt')}")

    # ------------------------------------------------------ [6/6] 无镜头分支
    print("\n[6/6] 没有已渲染镜头时，应给可读提示而不是崩")
    empty = ffmpeg.run_export(project, [], opts)
    need(empty.get("rendered") is False,
         f"无镜头时不该声称渲染成功：{empty.get('rendered')}",
         "无镜头时 rendered=False")
    need(bool(empty.get("message")),
         "无镜头时应给出可读提示", f"提示：{empty.get('message')}")

    print("\n" + "─" * 60)
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        return 1
    print("✓ 剪辑导出端到端通过（concat + scale/pad + 烧字幕 → 可播 MP4）")
    print("  真实环境里把镜头换成 H3 / 云端 Provider 的产物即可，导出逻辑完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
