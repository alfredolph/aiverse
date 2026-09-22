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


def detect() -> dict[str, Any]:
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"available": False, "path": None, "version": None,
                "hint": "未检测到 FFmpeg。安装后（并把 ffmpeg 加入 PATH）即可导出真实 MP4。"}
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=8)
        first = (out.stdout or "").splitlines()[0] if out.stdout else ""
        return {"available": True, "path": exe, "version": first, "hint": "FFmpeg 可用"}
    except Exception as e:
        return {"available": False, "path": exe, "version": None, "hint": f"FFmpeg 探测失败：{e}"}


def _aspect_size(aspect: str, resolution: str) -> str:
    base = _PRESET.get(resolution, "1280x720")
    w, h = (int(x) for x in base.split("x"))
    aw, ah = (float(x) for x in aspect.split(":"))
    if aw >= ah:
        nw = w
        nh = int(w * ah / aw / 2) * 2
    else:
        nh = h
        nw = int(h * aw / ah / 2) * 2
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

    video_files = []
    for s in shots:
        v = (s.get("payload") or {}).get("video") or {}
        if v.get("manifest"):
            video_files.append(v["manifest"])
        elif v.get("path"):
            video_files.append(v["path"])

    concat_rel = f"exports/{name}.concat.txt"
    lines = [f"file '{f}'" for f in video_files] if video_files else ["# 暂无已渲染镜头，接入真实视频 Provider 后自动填充"]
    store.write_text(pid, concat_rel, "\n".join(lines))

    out_rel = f"exports/{name}.{container.lower()}"
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_rel,
        "-vf", f"scale={size}:force_original_aspect_ratio=decrease,pad={size}:(ow-iw)/2:(oh-ih)/2",
        "-r", str(fps), "-c:v", codec, "-pix_fmt", "yuv420p", out_rel,
    ]
    plan = {
        "container": container, "resolution": resolution, "aspect": aspect,
        "output_size": size, "fps": fps, "codec": codec,
        "shots": len(shots), "video_files": len(video_files),
        "concat": concat_rel, "output": out_rel,
        "command": " ".join(cmd),
        "ffmpeg": detect(),
        "note": "镜头为占位产物时，导出的是镜头清单；接入 H3 / 云端 Provider 后可产出真实 MP4。",
    }
    store.write_json(pid, f"exports/{name}.export.json", plan)
    return plan


def run_export(project: dict, options: dict) -> dict[str, Any]:
    plan = build_export_plan(project, [], options)
    if not plan["ffmpeg"]["available"]:
        plan["rendered"] = False
        plan["message"] = plan["ffmpeg"]["hint"]
        return plan
    try:
        subprocess.run(plan["command"].split(), capture_output=True, text=True, timeout=1800)
        plan["rendered"] = True
        plan["message"] = "导出完成"
    except Exception as e:
        plan["rendered"] = False
        plan["message"] = f"导出失败：{e}"
    return plan
