"""媒体引擎：FFmpeg 适配 + 字幕 + 导出计划（文档 §29 / §30）。

本机没有 ffmpeg 时不会报错：仍会生成完整的导出计划（concat 清单 / 字幕 / 导出描述），
并在 UI 中提示「安装 FFmpeg 后即可一键渲染出片」。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..core import store
from ..core.config import CONTAINERS, RESOLUTIONS

_CODEC = {"MP4": "libx264", "H264": "libx264", "H265": "libx265", "AV1": "libsvtav1"}
_PRESET = {"480p": "854x480", "720p": "1280x720", "1080p": "1920x1080", "2K": "2560x1440", "4K": "3840x2160"}


def ffmpeg_path() -> Path | None:
    """找 ffmpeg：优先用一键部署装到 runtime/ 的那份，其次系统 PATH。"""
    try:
        from ..core.config import RUNTIME_DIR
        local = RUNTIME_DIR / "ffmpeg" / "bin" / "ffmpeg.exe"
        if local.exists():
            return local
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    return Path(exe) if exe else None


def ffprobe_path() -> Path | None:
    p = ffmpeg_path()
    if p:
        probe = p.with_name("ffprobe.exe")
        if probe.exists():
            return probe
    exe = shutil.which("ffprobe")
    return Path(exe) if exe else None


def detect() -> dict[str, Any]:
    p = ffmpeg_path()
    if not p:
        return {"available": False, "path": None, "version": None,
                "hint": "未检测到 FFmpeg。在「环境部署」里一键安装，或自行安装后加入 PATH。"}
    try:
        out = subprocess.run([str(p), "-version"], capture_output=True, text=True, timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        first = (out.stdout or "").splitlines()[0] if out.stdout else ""
        return {"available": True, "path": str(p), "version": first,
                "bundled": "runtime" in str(p).lower(), "hint": "FFmpeg 可用"}
    except Exception as e:
        return {"available": False, "path": str(p), "version": None, "hint": f"FFmpeg 探测失败：{e}"}


def _aspect_size(aspect: str, resolution: str) -> str:
    """按「短边 = 预设里那个数字」算输出尺寸。

    1080p 的预设是 1920x1080，短边 1080：
        横屏 16:9 → 1920x1080（与预设一致）
        竖屏 9:16 → 1080x1920（抖音/快手竖屏标准）
    之前竖屏是按「高 = 1080」算的，9:16 会得到 606x1080 —— 既不是任何标准尺寸，
    又白白丢掉一半纵向分辨率。漫剧默认就是 9:16，所以这个坑会天天踩。
    """
    base = _PRESET.get(resolution, "1280x720")
    w, h = (int(x) for x in base.split("x"))
    aw, ah = (float(x) for x in aspect.split(":"))
    short = min(w, h)
    if aw >= ah:
        nh = short
        nw = int(round(nh * aw / ah / 2)) * 2
    else:
        nw = short
        nh = int(round(nw * ah / aw / 2)) * 2
    return f"{nw}x{nh}"


def build_export_plan(project: dict, shots: list[dict], options: dict) -> dict[str, Any]:
    container = options.get("container", "MP4")
    resolution = options.get("resolution", "1080p")
    aspect = options.get("aspect") or project.get("aspect") or "16:9"
    fps = int(options.get("fps") or 24)
    codec = _CODEC.get(container, "libx264")
    size = _aspect_size(aspect, resolution)
    pid = project["id"]
    name = store.safe_name(project.get("name") or "project")
    base = store.resolve(pid)

    # 收集真实渲染出来的视频文件（H3 / 云端 Provider 产物）
    clips: list[str] = []
    placeholders = 0
    for s in shots:
        v = (s.get("payload") or {}).get("video") or {}
        rel = v.get("video")
        if rel and (base / rel).exists():
            clips.append(rel)
        elif v:
            placeholders += 1

    concat_rel = f"exports/{name}.concat.txt"
    if clips:
        body = "\n".join(f"file '{base / c}'" for c in clips)
    else:
        body = "# 暂无已渲染镜头。接入本地 H3 或云端视频 Provider 后自动填充。"
    store.write_text(pid, concat_rel, body)

    srt_rel = "subtitles/subtitle.srt"
    has_srt = (base / srt_rel).exists()
    out_rel = f"exports/{name}.{container.lower()}"

    exe = ffmpeg_path() or Path("ffmpeg")
    cmd = [str(exe), "-y", "-f", "concat", "-safe", "0", "-i", str(base / concat_rel)]
    # 注意 pad 的参数是 `pad=宽:高:x:y`，**不是** `pad=宽x高:...` ——
    # 写成 `pad=606x1080:...` 会被当成「宽度 = 表达式 606x1080」，
    # ffmpeg 直接报 Invalid chars 'x1080' 然后整条导出失败。
    # scale 用 `宽x高` 才是对的，两个滤镜的写法不一样，很容易抄错。
    # force_divisible_by=2 是必须的：scale 按比例缩出来的中间尺寸可能是奇数，
    # 那样 pad 的 (ow-iw)/2 就不是整数，会再报一次错，而且 x264 也不接受奇数尺寸。
    ow, oh = (int(x) for x in size.split("x"))
    vf = (f"scale={ow}:{oh}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
          f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2")
    if has_srt:
        esc_srt = str(base / srt_rel).replace("\\", "/").replace(":", "\\:")
        vf += f",subtitles='{esc_srt}'"
    cmd += ["-vf", vf, "-r", str(fps), "-c:v", codec, "-pix_fmt", "yuv420p"]
    if container in ("MP4", "H264"):
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += [str(base / out_rel)]

    plan = {
        "container": container, "resolution": resolution, "aspect": aspect,
        "output_size": size, "fps": fps, "codec": codec,
        "shots": len(shots), "video_files": len(clips), "placeholders": placeholders,
        "concat": concat_rel, "output": out_rel, "subtitle": srt_rel if has_srt else None,
        "command": " ".join(f'"{c}"' if " " in c else c for c in cmd),
        "argv": cmd,
        "ffmpeg": detect(),
        "note": ("将拼接 %d 个已渲染镜头%s并输出 %s"
                 % (len(clips),
                    "、烧录字幕" if has_srt else "",
                    container)
                 if clips else
                 "当前镜头是占位产物，导出的是镜头清单。完成「环境部署」接入本地 H3 后即可产出真实 MP4。"),
    }
    store.write_json(pid, f"exports/{name}.export.json", plan)
    return plan


def run_export(project: dict, shots: list[dict], options: dict) -> dict[str, Any]:
    """真正执行导出。没有 ffmpeg 或没有已渲染镜头时，只返回计划。"""
    plan = build_export_plan(project, shots, options)
    if not plan["ffmpeg"]["available"]:
        plan["rendered"] = False
        plan["message"] = plan["ffmpeg"]["hint"]
        return plan
    if not plan["video_files"]:
        plan["rendered"] = False
        plan["message"] = plan["note"]
        return plan

    base = store.resolve(project["id"])
    (base / "exports").mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(plan["argv"], capture_output=True, text=True, timeout=3600,
                           encoding="utf-8", errors="ignore",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and (base / plan["output"]).exists():
            out = base / plan["output"]
            plan["rendered"] = True
            plan["output_bytes"] = out.stat().st_size
            plan["output_size_human"] = _human(out.stat().st_size)
            plan["message"] = f"导出完成：{plan['output']}"
        else:
            plan["rendered"] = False
            plan["message"] = f"导出失败（退出码 {r.returncode}）：{(r.stderr or '')[-400:]}"
    except Exception as e:
        plan["rendered"] = False
        plan["message"] = f"导出异常：{e}"
    return plan


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
